/**
 * Canonical JSON encoding that is byte-for-byte compatible with the Python
 * Network Authority / node, which signs and verifies over:
 *
 *     json.dumps(obj, sort_keys=True, separators=(',', ':'))
 *
 * with the default `ensure_ascii=True`. Reproducing this exactly is what makes
 * Ed25519 signatures interoperate between this TypeScript node and the Python
 * mesh. The rules we must match:
 *
 *  - object keys sorted ascending by Unicode code point (Python sorts by
 *    code point too for str keys), recursively
 *  - no whitespace: item separator ",", key/value separator ":"
 *  - non-ASCII escaped as \uXXXX (and astral chars as surrogate pairs),
 *    matching json.dumps(ensure_ascii=True)
 *  - the standard short escapes for control chars and " and \
 *
 * IMPORTANT: we never re-format values such as datetimes. When verifying a
 * model (genesis block, join certificate) we canonicalize the JSON exactly as
 * received from the NA, with datetime fields kept as their on-the-wire strings.
 * That is the same string the Python side produced via
 * `model_dump(mode="json")` and therefore the same bytes it signed.
 */

export type JsonValue =
  | null
  | boolean
  | number
  | string
  | JsonValue[]
  | { [key: string]: JsonValue };

const ESCAPES: Record<string, string> = {
  '"': '\\"',
  "\\": "\\\\",
  "\b": "\\b",
  "\f": "\\f",
  "\n": "\\n",
  "\r": "\\r",
  "\t": "\\t",
};

/** Encode a JSON string the way Python's json.dumps does with ensure_ascii=True. */
function encodeString(s: string): string {
  let out = '"';
  for (let i = 0; i < s.length; i++) {
    const ch = s[i];
    const code = s.charCodeAt(i);
    const shortEscape = ESCAPES[ch];
    if (shortEscape !== undefined) {
      out += shortEscape;
    } else if (code < 0x20) {
      out += "\\u" + code.toString(16).padStart(4, "0");
    } else if (code < 0x7f) {
      // Printable ASCII (0x20..0x7e). 0x7f (DEL) is escaped by json.dumps? No:
      // json.dumps leaves 0x7f as a raw byte. We keep ASCII < 0x7f raw and
      // escape everything >= 0x7f to be safe and match ensure_ascii.
      out += ch;
    } else {
      // code >= 0x7f: escape as \uXXXX. charCodeAt already yields UTF-16 code
      // units, so astral characters are emitted as surrogate pairs exactly like
      // Python's ensure_ascii output.
      out += "\\u" + code.toString(16).padStart(4, "0");
    }
  }
  return out + '"';
}

/** Format a number the way Python's json.dumps would for ints we exchange. */
function encodeNumber(n: number): string {
  if (!Number.isFinite(n)) {
    throw new Error(`Cannot canonicalize non-finite number: ${n}`);
  }
  if (Number.isInteger(n)) {
    return String(n);
  }
  // Floats are only used by optional peer-announcement gossip. Python's repr of
  // floats can differ from JS for some values; we avoid signing/verifying
  // floats in the core flows. See README "Interop caveats".
  return String(n);
}

export function canonicalize(value: JsonValue): string {
  if (value === null) return "null";
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "number") return encodeNumber(value);
  if (typeof value === "string") return encodeString(value);
  if (Array.isArray(value)) {
    return "[" + value.map((v) => canonicalize(v)).join(",") + "]";
  }
  if (typeof value === "object") {
    const keys = Object.keys(value).sort(); // default sort = code-point order
    const parts = keys.map(
      (k) => encodeString(k) + ":" + canonicalize(value[k]),
    );
    return "{" + parts.join(",") + "}";
  }
  throw new Error(`Cannot canonicalize value of type ${typeof value}`);
}

/** Canonicalize an object after removing the given top-level keys (e.g. "signatures"). */
export function canonicalizeExcluding(
  value: Record<string, JsonValue>,
  exclude: string[],
): string {
  const copy: Record<string, JsonValue> = {};
  for (const k of Object.keys(value)) {
    if (!exclude.includes(k)) copy[k] = value[k];
  }
  return canonicalize(copy);
}
