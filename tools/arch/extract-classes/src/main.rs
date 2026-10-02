//! Deterministic class-model extractor.
//!
//! Parses Rust source with `syn` and emits a canonical class-model JSON on
//! stdout. This is the **as-built** side of the pre/post class diff
//! (architecture/lexicon-conformance.md is the sibling design for derivations;
//! this tool supports the `/explain` learning loop).
//!
//! Usage: extract-classes --src app/src --context expense_tracking
//!
//! Output schema:
//! {
//!   "context": "expense_tracking",
//!   "classes": [
//!     { "name", "kind": "class|enum|trait", "module", "visibility",
//!       "fields": [{"name","type","visibility"}],
//!       "variants": ["..."],
//!       "methods": [{"name","visibility","signature"}] }
//!   ],
//!   "relations": [{"from","to","kind":"composition|implementation|dependency"}]
//! }

use std::collections::{BTreeMap, BTreeSet};
use std::path::{Path, PathBuf};
use std::process::ExitCode;

use quote::ToTokens;
use serde::Serialize;
use syn::visit::Visit;
use syn::{Fields, ImplItem, Item, Type, Visibility};

#[derive(Serialize)]
struct Class {
    name: String,
    kind: &'static str,
    module: String,
    visibility: &'static str,
    fields: Vec<Field>,
    variants: Vec<String>,
    methods: Vec<Method>,
}

#[derive(Serialize)]
struct Field {
    name: String,
    #[serde(rename = "type")]
    type_: String,
    visibility: &'static str,
}

#[derive(Serialize)]
struct Method {
    name: String,
    visibility: &'static str,
    signature: String,
}

#[derive(Serialize)]
struct Relation {
    from: String,
    to: String,
    kind: &'static str,
}

#[derive(Serialize)]
struct Model {
    context: String,
    classes: Vec<Class>,
    relations: Vec<Relation>,
}

fn visibility(v: &Visibility) -> &'static str {
    match v {
        Visibility::Public(_) => "public",
        Visibility::Restricted(_) => "restricted",
        Visibility::Inherited => "private",
    }
}

fn type_string(ty: &Type) -> String {
    let raw = ty.to_token_stream().to_string();
    // Collapse the token spacing into readable Rust.
    let mut out = String::new();
    let mut prev_space = false;
    for ch in raw.chars() {
        if ch == ' ' {
            prev_space = true;
            continue;
        }
        let tight_before = matches!(ch, '<' | '>' | ',' | ')' | ']' | '&' | ':' | ';' | '(');
        if prev_space && !tight_before && !out.ends_with('<') && !out.ends_with('&') && !out.ends_with(':') {
            out.push(' ');
        }
        out.push(ch);
        prev_space = false;
    }
    out
}

/// Collect the last path segment idents used in a type, to find field relations.
#[derive(Default)]
struct TypeIdents(Vec<String>);
impl<'ast> Visit<'ast> for TypeIdents {
    fn visit_type_path(&mut self, node: &'ast syn::TypePath) {
        if let Some(seg) = node.path.segments.last() {
            self.0.push(seg.ident.to_string());
        }
        syn::visit::visit_type_path(self, node);
    }

    /// `&dyn Trait` is a `TraitBound`, not a `TypePath`; capture it too so
    /// method-parameter port objects become `dependency` edges.
    fn visit_trait_bound(&mut self, node: &'ast syn::TraitBound) {
        if let Some(seg) = node.path.segments.last() {
            self.0.push(seg.ident.to_string());
        }
        syn::visit::visit_trait_bound(self, node);
    }
}

fn field_type_names(ty: &Type) -> Vec<String> {
    let mut v = TypeIdents::default();
    v.visit_type(ty);
    v.0
}

/// Type idents referenced by a method signature (parameters and return type).
/// These are `dependency` edges: the declaring type needs the referenced type
/// to exist, but does not own it (unlike a field `composition`).
fn signature_type_names(sig: &syn::Signature) -> Vec<String> {
    let mut names = Vec::new();
    for arg in &sig.inputs {
        if let syn::FnArg::Typed(pt) = arg {
            names.extend(field_type_names(&pt.ty));
        }
    }
    if let syn::ReturnType::Type(_, ty) = &sig.output {
        names.extend(field_type_names(ty));
    }
    names
}

/// Build the relation set: field `composition`, trait `implementation`, and
/// method-signature `dependency`. A stronger edge (composition or
/// implementation) between the same pair suppresses a redundant dependency.
fn build_relations(
    field_types: &[(String, Vec<String>)],
    method_refs: &[(String, Vec<String>)],
    impls: &[(String, String)],
    known: &BTreeSet<String>,
) -> BTreeSet<(String, String, &'static str)> {
    let mut relations: BTreeSet<(String, String, &'static str)> = BTreeSet::new();
    for (from, refs) in field_types {
        for to in refs {
            if to != from && known.contains(to) {
                relations.insert((from.clone(), to.clone(), "composition"));
            }
        }
    }
    for (from, to) in impls {
        if known.contains(to) {
            relations.insert((from.clone(), to.clone(), "implementation"));
        }
    }
    for (from, refs) in method_refs {
        for to in refs {
            if to == from || !known.contains(to) {
                continue;
            }
            let composed = relations.contains(&(from.clone(), to.clone(), "composition"));
            let implemented = relations.contains(&(from.clone(), to.clone(), "implementation"));
            if !composed && !implemented {
                relations.insert((from.clone(), to.clone(), "dependency"));
            }
        }
    }
    relations
}

fn method_signature(sig: &syn::Signature) -> String {
    let inputs = sig
        .inputs
        .iter()
        .map(|arg| match arg {
            syn::FnArg::Receiver(r) => {
                let mut s = String::new();
                if r.reference.is_some() {
                    s.push('&');
                }
                if r.mutability.is_some() {
                    s.push_str("mut ");
                }
                s.push_str("self");
                s
            }
            syn::FnArg::Typed(pt) => {
                let pat = pt.pat.to_token_stream().to_string().replace(' ', "");
                format!("{}: {}", pat, type_string(&pt.ty))
            }
        })
        .collect::<Vec<_>>()
        .join(", ");
    let output = match &sig.output {
        syn::ReturnType::Default => String::new(),
        syn::ReturnType::Type(_, ty) => format!(" -> {}", type_string(ty)),
    };
    format!("{}({}){}", sig.ident, inputs, output)
}

fn module_of(src_root: &Path, file: &Path) -> String {
    let rel = file.strip_prefix(src_root).unwrap_or(file);
    let mut parts: Vec<String> = rel
        .components()
        .map(|c| c.as_os_str().to_string_lossy().to_string())
        .collect();
    if let Some(last) = parts.last_mut() {
        *last = last.trim_end_matches(".rs").to_string();
    }
    if matches!(parts.last().map(String::as_str), Some("mod") | Some("lib") | Some("main")) {
        parts.pop();
    }
    parts.retain(|p| !p.is_empty());
    parts.join("::")
}

fn walk_rs(dir: &Path, out: &mut Vec<PathBuf>) {
    let Ok(entries) = std::fs::read_dir(dir) else {
        return;
    };
    for entry in entries.flatten() {
        let path = entry.path();
        if path.is_dir() {
            walk_rs(&path, out);
        } else if path.extension().is_some_and(|e| e == "rs") {
            out.push(path);
        }
    }
}

fn main() -> ExitCode {
    let mut args = std::env::args().skip(1);
    let mut src = PathBuf::from("src");
    let mut context = String::from("unknown");
    while let Some(arg) = args.next() {
        match arg.as_str() {
            "--src" => src = PathBuf::from(args.next().unwrap_or_default()),
            "--context" => context = args.next().unwrap_or_default(),
            other => {
                eprintln!("unknown argument: {other}");
                return ExitCode::from(2);
            }
        }
    }

    let mut files = Vec::new();
    walk_rs(&src, &mut files);
    files.sort();

    let mut classes: BTreeMap<String, Class> = BTreeMap::new();
    // type name -> directly implemented trait names
    let mut impls: Vec<(String, String)> = Vec::new();
    // type name -> field type idents
    let mut field_types: Vec<(String, Vec<String>)> = Vec::new();
    // inherent methods collected across files, applied after all types are known
    let mut inherent: Vec<(String, Vec<Method>)> = Vec::new();
    // type name -> type idents referenced in its method signatures (params + return)
    let mut method_refs: Vec<(String, Vec<String>)> = Vec::new();

    for file in &files {
        let Ok(text) = std::fs::read_to_string(file) else {
            continue;
        };
        let Ok(ast) = syn::parse_file(&text) else {
            eprintln!("warning: could not parse {}", file.display());
            continue;
        };
        let module = module_of(&src, file);

        for item in &ast.items {
            match item {
                Item::Struct(s) => {
                    let mut fields = Vec::new();
                    let mut refs = Vec::new();
                    if let Fields::Named(named) = &s.fields {
                        for f in &named.named {
                            let ty = &f.ty;
                            fields.push(Field {
                                name: f.ident.as_ref().map(|i| i.to_string()).unwrap_or_default(),
                                type_: type_string(ty),
                                visibility: visibility(&f.vis),
                            });
                            refs.extend(field_type_names(ty));
                        }
                    }
                    field_types.push((s.ident.to_string(), refs));
                    classes.insert(
                        s.ident.to_string(),
                        Class {
                            name: s.ident.to_string(),
                            kind: "class",
                            module: module.clone(),
                            visibility: visibility(&s.vis),
                            fields,
                            variants: Vec::new(),
                            methods: Vec::new(),
                        },
                    );
                }
                Item::Enum(e) => {
                    let mut refs = Vec::new();
                    let variants = e
                        .variants
                        .iter()
                        .map(|v| {
                            for f in &v.fields {
                                refs.extend(field_type_names(&f.ty));
                            }
                            v.ident.to_string()
                        })
                        .collect();
                    field_types.push((e.ident.to_string(), refs));
                    classes.insert(
                        e.ident.to_string(),
                        Class {
                            name: e.ident.to_string(),
                            kind: "enum",
                            module: module.clone(),
                            visibility: visibility(&e.vis),
                            fields: Vec::new(),
                            variants,
                            methods: Vec::new(),
                        },
                    );
                }
                Item::Trait(t) => {
                    let methods = t
                        .items
                        .iter()
                        .filter_map(|it| match it {
                            syn::TraitItem::Fn(f) => Some(Method {
                                name: f.sig.ident.to_string(),
                                visibility: "public",
                                signature: method_signature(&f.sig),
                            }),
                            _ => None,
                        })
                        .collect();
                    let mut refs = Vec::new();
                    for it in &t.items {
                        if let syn::TraitItem::Fn(f) = it {
                            refs.extend(signature_type_names(&f.sig));
                        }
                    }
                    method_refs.push((t.ident.to_string(), refs));
                    classes.insert(
                        t.ident.to_string(),
                        Class {
                            name: t.ident.to_string(),
                            kind: "trait",
                            module: module.clone(),
                            visibility: visibility(&t.vis),
                            fields: Vec::new(),
                            variants: Vec::new(),
                            methods,
                        },
                    );
                }
                Item::Impl(imp) => {
                    let self_ty = type_string(&imp.self_ty);
                    if let Some((_, path, _)) = &imp.trait_ {
                        if let Some(seg) = path.segments.last() {
                            impls.push((self_ty.clone(), seg.ident.to_string()));
                        }
                    }
                    // Method-signature references feed `dependency` relations,
                    // for both trait and inherent impls.
                    let mut refs = Vec::new();
                    for item in &imp.items {
                        if let ImplItem::Fn(f) = item {
                            refs.extend(signature_type_names(&f.sig));
                        }
                    }
                    method_refs.push((self_ty.clone(), refs));
                    // Inherent methods attach to the class (applied after all files).
                    if imp.trait_.is_none() {
                        let mut methods = Vec::new();
                        for item in &imp.items {
                            if let ImplItem::Fn(f) = item {
                                methods.push(Method {
                                    name: f.sig.ident.to_string(),
                                    visibility: visibility(&f.vis),
                                    signature: method_signature(&f.sig),
                                });
                            }
                        }
                        inherent.push((self_ty.clone(), methods));
                    }
                }
                _ => {}
            }
        }
    }

    let known: BTreeSet<String> = classes.keys().cloned().collect();
    for (ty, methods) in inherent {
        if let Some(class) = classes.get_mut(&ty) {
            class.methods.extend(methods);
        }
    }
    let relations = build_relations(&field_types, &method_refs, &impls, &known);

    let model = Model {
        context,
        classes: classes.into_values().collect(),
        relations: relations
            .into_iter()
            .map(|(from, to, kind)| Relation { from, to, kind })
            .collect(),
    };

    match serde_json::to_string_pretty(&model) {
        Ok(json) => {
            println!("{json}");
            ExitCode::SUCCESS
        }
        Err(e) => {
            eprintln!("failed to serialize model: {e}");
            ExitCode::from(1)
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn known(names: &[&str]) -> BTreeSet<String> {
        names.iter().map(|s| s.to_string()).collect()
    }

    #[test]
    fn dependency_is_inferred_from_method_signatures() {
        let known = known(&["Handler", "Port", "Form", "Command", "Field"]);
        let field_types = vec![("Form".to_string(), vec!["Field".to_string()])];
        let method_refs = vec![
            ("Handler".to_string(), vec!["Port".to_string()]),
            (
                "Form".to_string(),
                vec!["Command".to_string(), "Field".to_string()],
            ),
        ];
        let impls: Vec<(String, String)> = Vec::new();
        let rels = build_relations(&field_types, &method_refs, &impls, &known);

        assert!(rels.contains(&("Handler".into(), "Port".into(), "dependency")));
        assert!(rels.contains(&("Form".into(), "Command".into(), "dependency")));
        // A field composition already expresses the Form -> Field dependency.
        assert!(rels.contains(&("Form".into(), "Field".into(), "composition")));
        assert!(!rels.contains(&("Form".into(), "Field".into(), "dependency")));
    }

    #[test]
    fn self_and_unknown_types_are_ignored() {
        let rels = build_relations(
            &[],
            &[(
                "A".to_string(),
                vec!["A".to_string(), "Unknown".to_string()],
            )],
            &[],
            &known(&["A"]),
        );
        assert!(rels.is_empty());
    }

    #[test]
    fn implementation_suppresses_dependency() {
        let rels = build_relations(
            &[],
            &[("Impl".to_string(), vec!["Trait".to_string()])],
            &[("Impl".to_string(), "Trait".to_string())],
            &known(&["Impl", "Trait"]),
        );
        assert!(rels.contains(&("Impl".into(), "Trait".into(), "implementation")));
        assert!(!rels.contains(&("Impl".into(), "Trait".into(), "dependency")));
    }

    #[test]
    fn signature_captures_trait_object_bounds_and_returns() {
        let sig: syn::Signature = syn::parse_quote!(
            fn execute(
                &self,
                store: &dyn StartingBalanceStore,
                cmd: &SetStartingBalances,
            ) -> Result<(), CommandError>
        );
        let names = signature_type_names(&sig);
        for expected in ["StartingBalanceStore", "SetStartingBalances", "CommandError"] {
            assert!(
                names.contains(&expected.to_string()),
                "missing {expected} in {names:?}"
            );
        }
    }
}
