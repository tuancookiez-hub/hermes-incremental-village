//! Python-compatible text formatting: `repr`, `str`, float repr, `strip` and slicing by code point.

use serde_json::Value;

/// Python's `repr(float)`.
pub fn float_repr(x: f64) -> String {
    if x.is_nan() {
        return "nan".into();
    }
    if x.is_infinite() {
        return if x > 0.0 { "inf".into() } else { "-inf".into() };
    }
    if x == 0.0 {
        return if x.is_sign_negative() { "-0.0".into() } else { "0.0".into() };
    }
    let sign = if x < 0.0 { "-" } else { "" };
    let s = format!("{:e}", x.abs());
    let (mant, exp) = s.split_once('e').unwrap_or((&s, "0"));
    let exp: i32 = exp.parse().unwrap_or(0);
    let digits: String = mant.chars().filter(|c| *c != '.').collect();
    let decpt = exp + 1;
    let n = digits.len() as i32;
    let body = if -4 < decpt && decpt <= 16 {
        if decpt <= 0 {
            format!("0.{}{}", "0".repeat((-decpt) as usize), digits)
        } else if decpt >= n {
            format!("{}{}.0", digits, "0".repeat((decpt - n) as usize))
        } else {
            format!("{}.{}", &digits[..decpt as usize], &digits[decpt as usize..])
        }
    } else {
        let e = decpt - 1;
        let rest = &digits[1..];
        let m = if rest.is_empty() { digits[..1].to_string() } else { format!("{}.{}", &digits[..1], rest) };
        format!("{}e{}{:02}", m, if e < 0 { '-' } else { '+' }, e.abs())
    };
    format!("{}{}", sign, body)
}

fn printable(c: char) -> bool {
    let u = c as u32;
    if u < 0x20 || (0x7f..=0xa0).contains(&u) || u == 0xad {
        return false;
    }
    if u < 0x7f {
        return true;
    }
    !matches!(u,
        0x600..=0x605 | 0x61c | 0x6dd | 0x70f | 0x8e2 | 0x1680 | 0x180e
        | 0x2000..=0x200f | 0x2028..=0x202f | 0x205f..=0x206f | 0x3000
        | 0xfeff | 0xfff9..=0xfffb | 0x110bd | 0x110cd | 0xe0001 | 0xe0020..=0xe007f
        | 0xe000..=0xf8ff | 0xf0000..=0xffffd | 0x100000..=0x10fffd)
}

/// Python's `repr(str)`.
pub fn str_repr(s: &str) -> String {
    let quote = if s.contains('\'') && !s.contains('"') { '"' } else { '\'' };
    let mut out = String::with_capacity(s.len() + 2);
    out.push(quote);
    for c in s.chars() {
        match c {
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            c if c == quote => {
                out.push('\\');
                out.push(c);
            }
            c if printable(c) => out.push(c),
            c => {
                let u = c as u32;
                if u < 0x100 {
                    out.push_str(&format!("\\x{:02x}", u));
                } else if u < 0x10000 {
                    out.push_str(&format!("\\u{:04x}", u));
                } else {
                    out.push_str(&format!("\\U{:08x}", u));
                }
            }
        }
    }
    out.push(quote);
    out
}

fn number_str(n: &serde_json::Number) -> String {
    if let Some(i) = n.as_i64() {
        i.to_string()
    } else if let Some(u) = n.as_u64() {
        u.to_string()
    } else {
        float_repr(n.as_f64().unwrap_or(f64::NAN))
    }
}

/// Python's `repr(value)` for a JSON-derived value.
pub fn repr(v: &Value) -> String {
    match v {
        Value::Null => "None".into(),
        Value::Bool(b) => if *b { "True".into() } else { "False".into() },
        Value::Number(n) => number_str(n),
        Value::String(s) => str_repr(s),
        Value::Array(a) => format!("[{}]", a.iter().map(repr).collect::<Vec<_>>().join(", ")),
        Value::Object(m) => format!(
            "{{{}}}",
            m.iter().map(|(k, v)| format!("{}: {}", str_repr(k), repr(v))).collect::<Vec<_>>().join(", ")
        ),
    }
}

/// Python's `str(value)` (and what an f-string prints for it).
pub fn pystr(v: &Value) -> String {
    match v {
        Value::String(s) => s.clone(),
        other => repr(other),
    }
}

fn is_space(c: char) -> bool {
    matches!(c,
        '\t' | '\n' | '\x0b' | '\x0c' | '\r' | '\x1c'..='\x1f' | ' ' | '\u{85}' | '\u{a0}' | '\u{1680}'
        | '\u{2000}'..='\u{200a}' | '\u{2028}' | '\u{2029}' | '\u{202f}' | '\u{205f}' | '\u{3000}')
}

/// Python's `str.strip()`.
pub fn strip(s: &str) -> &str {
    s.trim_matches(is_space)
}

/// `s[:n]` by code points.
pub fn head(s: &str, n: usize) -> String {
    s.chars().take(n).collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn floats() {
        assert_eq!(float_repr(1000.0), "1000.0");
        assert_eq!(float_repr(0.1), "0.1");
        assert_eq!(float_repr(1e16), "1e+16");
        assert_eq!(float_repr(1.5e-5), "1.5e-05");
        assert_eq!(float_repr(123456789.125), "123456789.125");
        assert_eq!(float_repr(-0.0001), "-0.0001");
        assert_eq!(float_repr(0.00001), "1e-05");
        assert_eq!(float_repr(9999999999999998.0), "9999999999999998.0");
    }

    #[test]
    fn strings() {
        assert_eq!(str_repr("a'b"), "\"a'b\"");
        assert_eq!(str_repr("a'b\"c"), "'a\\'b\"c'");
        assert_eq!(str_repr("tab\there"), "'tab\\there'");
        assert_eq!(str_repr("caf\u{e9}"), "'caf\u{e9}'");
        assert_eq!(str_repr("\u{7}"), "'\\x07'");
    }

    #[test]
    fn values() {
        let v: Value = serde_json::from_str(r#"{"a": [1, 2.5, null, true, "x"]}"#).unwrap();
        assert_eq!(repr(&v), "{'a': [1, 2.5, None, True, 'x']}");
        assert_eq!(pystr(&Value::Null), "None");
    }
}
