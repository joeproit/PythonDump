#!/usr/bin/env python3
"""der-dump.py: dump ASN.1 DER/BER (CMS, PKCS#7, X.509) as an indented tree.

Scenario: inspect CMS/PKCS#7 specimens to see exactly which signed attribute,
          length or INTEGER encoding a verifier is choking on; also a quick
          cert/CMS reader on boxes without openssl.
Origin:   Cyguin adversarial conformance research: PSCertPatterns (May 2026)
          and PSCMSPatterns (June 2026, RFC 5652 SignedData specimens).
Written:  2026-11-21

Reads a file or stdin ("-"), PEM or raw DER. Each line shows the byte offset,
the total TLV size, then the tag and a decoded value. OIDs get names for the
common CMS/PKI set. Encodings that DER forbids are flagged inline, which is
handy when inspecting mutated specimens:

  [indefinite length]      BER only
  [non-minimal length]     long-form length where short form (or fewer bytes) fits
  [non-minimal INTEGER]    redundant leading 00 / FF byte, or empty content
  [bad BOOLEAN]            value other than 00 or FF

  der-dump.py signed.p7s
  der-dump.py --octets signed.p7s    # also descend into OCTET STRING / BIT STRING contents
  openssl cms -sign ... -outform DER | der-dump.py -
  der-dump.py --strict specimen.der  # exit 1 if anything was flagged

Deps: none (stdlib only).
"""
import argparse
import base64
import binascii
import os
import re
import sys

UNIVERSAL = {1: "BOOLEAN", 2: "INTEGER", 3: "BIT STRING", 4: "OCTET STRING", 5: "NULL",
             6: "OBJECT IDENTIFIER", 10: "ENUMERATED", 12: "UTF8String", 16: "SEQUENCE",
             17: "SET", 19: "PrintableString", 20: "T61String", 22: "IA5String",
             23: "UTCTime", 24: "GeneralizedTime", 26: "VisibleString", 28: "UniversalString",
             30: "BMPString"}
STRING_TAGS = {12, 19, 20, 22, 26}
CLASSES = ["", "APPLICATION ", "", "PRIVATE "]

OIDS = {
    "1.2.840.113549.1.7.1": "data",
    "1.2.840.113549.1.7.2": "signedData",
    "1.2.840.113549.1.7.3": "envelopedData",
    "1.2.840.113549.1.9.1": "emailAddress",
    "1.2.840.113549.1.9.3": "contentType",
    "1.2.840.113549.1.9.4": "messageDigest",
    "1.2.840.113549.1.9.5": "signingTime",
    "1.2.840.113549.1.9.6": "counterSignature",
    "1.2.840.113549.1.9.16.2.12": "signingCertificate (ESSCertID)",
    "1.2.840.113549.1.9.16.2.47": "signingCertificateV2 (ESSCertIDv2)",
    "1.2.840.113549.1.1.1": "rsaEncryption",
    "1.2.840.113549.1.1.5": "sha1WithRSAEncryption",
    "1.2.840.113549.1.1.10": "RSASSA-PSS",
    "1.2.840.113549.1.1.11": "sha256WithRSAEncryption",
    "1.2.840.113549.1.1.12": "sha384WithRSAEncryption",
    "1.2.840.113549.1.1.13": "sha512WithRSAEncryption",
    "1.2.840.10045.2.1": "ecPublicKey",
    "1.2.840.10045.3.1.7": "prime256v1 (P-256)",
    "1.3.132.0.34": "secp384r1 (P-384)",
    "1.2.840.10045.4.3.2": "ecdsa-with-SHA256",
    "1.2.840.10045.4.3.3": "ecdsa-with-SHA384",
    "1.3.101.112": "Ed25519",
    "1.3.14.3.2.26": "sha1",
    "2.16.840.1.101.3.4.2.1": "sha256",
    "2.16.840.1.101.3.4.2.2": "sha384",
    "2.16.840.1.101.3.4.2.3": "sha512",
    "2.5.4.3": "commonName",
    "2.5.4.6": "countryName",
    "2.5.4.7": "localityName",
    "2.5.4.8": "stateOrProvinceName",
    "2.5.4.10": "organizationName",
    "2.5.4.11": "organizationalUnitName",
    "2.5.29.14": "subjectKeyIdentifier",
    "2.5.29.15": "keyUsage",
    "2.5.29.17": "subjectAltName",
    "2.5.29.19": "basicConstraints",
    "2.5.29.35": "authorityKeyIdentifier",
    "2.5.29.37": "extKeyUsage",
    "1.3.6.1.5.5.7.3.1": "serverAuth",
    "1.3.6.1.5.5.7.3.3": "codeSigning",
    "1.3.6.1.5.5.7.3.4": "emailProtection",
}


class DerError(Exception):
    pass


def read_header(buf, pos, end):
    """Return (cls, constructed, tag, length|None, header_len, flags)."""
    start, flags = pos, []
    if pos >= end:
        raise DerError(f"truncated at offset {pos}")
    b = buf[pos]
    pos += 1
    cls, constructed, tag = b >> 6, bool(b & 0x20), b & 0x1F
    if tag == 0x1F:
        tag = 0
        while True:
            if pos >= end:
                raise DerError(f"truncated tag at offset {start}")
            x = buf[pos]
            pos += 1
            tag = (tag << 7) | (x & 0x7F)
            if not x & 0x80:
                break
    if pos >= end:
        raise DerError(f"truncated length at offset {start}")
    first = buf[pos]
    pos += 1
    if first == 0x80:
        length = None
        flags.append("indefinite length")
    elif first & 0x80:
        n = first & 0x7F
        if n == 0x7F or pos + n > end:
            raise DerError(f"bad length field at offset {start}")
        raw = buf[pos:pos + n]
        pos += n
        length = int.from_bytes(raw, "big")
        if length < 0x80 or raw[0] == 0:
            flags.append("non-minimal length")
    else:
        length = first
    return cls, constructed, tag, length, pos - start, flags


def decode_oid(content):
    if not content:
        return "<empty>"
    subs, val = [], 0
    for byte in content:
        val = (val << 7) | (byte & 0x7F)
        if not byte & 0x80:
            subs.append(val)
            val = 0
    if content[-1] & 0x80:
        return "<truncated>"
    first = subs[0]
    head = [min(first // 40, 2)]
    head.append(first - 40 * head[0])
    return ".".join(str(x) for x in head + subs[1:])


def hexp(data, limit):
    s = data[:limit].hex()
    return s + ("..." if len(data) > limit else "")


def describe(tag, content, limit, flags):
    """Decoded value text for a primitive universal type."""
    if tag == 1:
        if content not in (b"\x00", b"\xff"):
            flags.append("bad BOOLEAN")
            return "0x" + content.hex()
        return "TRUE" if content == b"\xff" else "FALSE"
    if tag in (2, 10):
        if not content or (len(content) > 1 and (
                (content[0] == 0 and content[1] < 0x80) or (content[0] == 0xFF and content[1] >= 0x80))):
            flags.append("non-minimal INTEGER")
        if not content:
            return ""
        return str(int.from_bytes(content, "big", signed=True)) if len(content) <= 8 else "0x" + hexp(content, limit)
    if tag == 5:
        return ""
    if tag == 6:
        oid = decode_oid(content)
        return f"{oid} ({OIDS[oid]})" if oid in OIDS else oid
    if tag in STRING_TAGS:
        return repr(content.decode("utf-8", errors="replace"))
    if tag in (23, 24):
        return content.decode("ascii", errors="replace")
    if tag == 30:
        return repr(content.decode("utf-16-be", errors="replace"))
    if tag == 3:
        unused = content[0] if content else 0
        return f"{max(len(content) - 1, 0)} bytes, {unused} unused bits  {hexp(content[1:], limit)}"
    if tag == 4:
        return f"{len(content)} bytes  {hexp(content, limit)}"
    return hexp(content, limit)


def parses_cleanly(buf, pos, end):
    """True if buf[pos:end] is a complete run of definite-length TLVs."""
    if pos >= end:
        return False
    while pos < end:
        try:
            cls, constructed, tag, length, hdr, _ = read_header(buf, pos, end)
        except DerError:
            return False
        if length is None or (cls == 0 and tag == 0) or pos + hdr + length > end:
            return False
        if constructed and length and not parses_cleanly(buf, pos + hdr, pos + hdr + length):
            return False
        pos += hdr + length
    return True


class Dumper:
    def __init__(self, buf, octets, limit):
        self.buf, self.octets, self.limit = buf, octets, limit
        self.flagged = 0
        self.out = sys.stdout

    def emit(self, pos, size, depth, label, value, flags):
        self.flagged += len(flags)
        tail = "".join(f"  [{f}]" for f in flags)
        self.out.write(f"{pos:6d} {size:6d}  {'  ' * depth}{label}{(' ' + value) if value else ''}{tail}\n")

    def walk(self, pos, end, depth, indefinite=False):
        buf = self.buf
        while pos < end:
            if indefinite and buf[pos:pos + 2] == b"\x00\x00":
                self.emit(pos, 2, depth - 1, "END-OF-CONTENTS", "", [])
                return pos + 2
            cls, constructed, tag, length, hdr, flags = read_header(buf, pos, end)
            if cls == 0:
                label = UNIVERSAL.get(tag, f"UNIVERSAL {tag}")
            else:
                label = f"[{CLASSES[cls]}{tag}]"
            body = pos + hdr
            if length is None:
                if not constructed:
                    raise DerError(f"indefinite length on primitive at offset {pos}")
                self.emit(pos, hdr, depth, label, "(indefinite)", flags)
                pos = self.walk(body, end, depth + 1, True)
                continue
            stop = body + length
            if stop > end:
                raise DerError(f"length overruns buffer at offset {pos} (needs {stop - end} more bytes)")
            content = buf[body:stop]
            if constructed:
                self.emit(pos, hdr + length, depth, label, "", flags)
                self.walk(body, stop, depth + 1)
            else:
                value = describe(tag, content, self.limit, flags) if cls == 0 else \
                    f"{len(content)} bytes  {hexp(content, self.limit)}"
                self.emit(pos, hdr + length, depth, label, value, flags)
                if self.octets and cls == 0 and tag in (3, 4):
                    inner = body + (1 if tag == 3 else 0)
                    if (tag == 4 or content[:1] == b"\x00") and parses_cleanly(buf, inner, stop):
                        self.walk(inner, stop, depth + 1)
            pos = stop
        if indefinite:
            raise DerError("missing END-OF-CONTENTS marker")
        return pos


def load(data):
    if data.lstrip().startswith(b"-----BEGIN"):
        m = re.search(rb"-----BEGIN [^-]+-----(.*?)-----END", data, re.S)
        if not m:
            raise DerError("malformed PEM block")
        try:
            return base64.b64decode(b"".join(m.group(1).split()), validate=True)
        except binascii.Error as exc:
            raise DerError(f"bad base64 in PEM: {exc}")
    return data


def main():
    ap = argparse.ArgumentParser(description="Dump ASN.1 DER/BER as a tree")
    ap.add_argument("file", help="DER or PEM file, or - for stdin")
    ap.add_argument("--octets", action="store_true", help="descend into OCTET/BIT STRING contents")
    ap.add_argument("--max-hex", type=int, default=24, help="hex bytes shown per value")
    ap.add_argument("--strict", action="store_true", help="exit 1 if any DER violation was flagged")
    args = ap.parse_args()

    try:
        raw = sys.stdin.buffer.read() if args.file == "-" else open(args.file, "rb").read()
        buf = load(raw)
        if not buf:
            raise DerError("empty input")
        dumper = Dumper(buf, args.octets, args.max_hex)
        print(f"{'OFFSET':>6} {'SIZE':>6}  STRUCTURE")
        dumper.walk(0, len(buf), 0)
        sys.stdout.flush()
    except BrokenPipeError:  # e.g. piped into head
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        return 0
    except (DerError, OSError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2
    if dumper.flagged:
        print(f"[WARN] {dumper.flagged} DER violation(s) flagged", file=sys.stderr)
        if args.strict:
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
