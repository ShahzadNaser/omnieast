#!/usr/bin/env python3
"""Merge / pull request security check. WARN ONLY: it never blocks a merge.

Looks only at the Python lines a merge request adds or changes and flags:
  W1  a whitelisted server function with no visible permission check
  W2  a whitelisted function open to guests (allow_guest=True)
  S1  SQL built from strings (.format, f-string, % or +) instead of parameters
  P1  ignore_permissions inside a whitelisted function
  K1  a password, token, key or secret written in the code

Usage: python3 ci/security_check.py <base_sha_or_ref> <head_sha_or_ref>
Exit code 1 when something is flagged. The CI job is set so a red result only
warns (GitLab allow_failure: true, GitHub continue-on-error: true).
On GitHub Actions each finding is also shown as a warning on the changed file.
"""

import ast
import os
import re
import subprocess
import sys

# Calls or names that show the function checks who is calling
PERMISSION_HINTS = (
	"only_for", "has_permission", "check_permission", "PermissionError", "frappe.get_list",
	"get_roles", "check_page_access", "check_portal_access", "is_valid_otp", "deny(",
)
SECRET_RE = re.compile(
	r"""(?ix)
	(?:password|passwd|pwd|secret|token|api_?key|client_?secret|authorization)\s*[\"']?\s*[:=]\s*[\"'][^\"'\s]{8,}[\"']
	| [\"'](?:bearer|basic)\s+[a-z0-9+/=._-]{12,}[\"']
	"""
)
SECRET_OK = re.compile(r"get_password|get_decrypted_password|get_single_value|get_value|getenv|environ|frappe\.conf", re.I)

CODES = "W1 no permission check, W2 open to guests, S1 SQL injection risk, P1 ignore_permissions, K1 secret in code."


def git(*args):
	return subprocess.run(["git"] + list(args), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
						  check=False).stdout.decode("utf-8", "replace")


def changed_lines(base, head):
	"""{path: set(line numbers added or changed in head)} for .py files."""
	out, path = {}, None
	for line in git("diff", "-U0", "--no-color", base, head, "--", "*.py").splitlines():
		if line.startswith("+++ "):
			path = line[6:] if line.startswith("+++ b/") else None
			if path:
				out.setdefault(path, set())
		elif line.startswith("@@") and path:
			m = re.search(r"\+(\d+)(?:,(\d+))?", line)
			start, count = int(m.group(1)), int(m.group(2) or 1)
			out[path].update(range(start, start + count))
	return out


def is_whitelist(dec):
	target = dec.func if isinstance(dec, ast.Call) else dec
	return isinstance(target, ast.Attribute) and target.attr == "whitelist" or \
		isinstance(target, ast.Name) and target.id == "whitelist"


def allows_guest(dec):
	return isinstance(dec, ast.Call) and any(
		k.arg == "allow_guest" and isinstance(k.value, ast.Constant) and k.value.value is True
		for k in dec.keywords)


def is_string_built(node):
	if isinstance(node, ast.JoinedStr):
		return True
	if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Mod, ast.Add)):
		return True
	if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "format":
		return True
	return False


def scan_file(path, lines_changed, source):
	findings = []
	try:
		tree = ast.parse(source)
	except SyntaxError as e:
		return [(path, e.lineno or 0, "--", "file does not parse: " + str(e.msg))]
	src_lines = source.splitlines()

	def touched(node):
		end = getattr(node, "end_lineno", node.lineno)
		return any(n in lines_changed for n in range(node.lineno, end + 1))

	for node in ast.walk(tree):
		if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
			wl = [d for d in node.decorator_list if is_whitelist(d)]
			if not wl or not touched(node):
				continue
			end = getattr(node, "end_lineno", node.lineno)
			body = "\n".join(src_lines[node.lineno - 1:end])
			if any(allows_guest(d) for d in wl):
				findings.append((path, node.lineno, "W2", "%s() is open to guests (allow_guest=True): "
								 "check it really has to be public" % node.name))
			if not any(h in body for h in PERMISSION_HINTS):
				findings.append((path, node.lineno, "W1", "%s() is whitelisted but has no visible permission "
								 "check (frappe.only_for / has_permission / check_permission / role check)" % node.name))
			for sub in ast.walk(node):
				if isinstance(sub, ast.keyword) and sub.arg == "ignore_permissions" and \
						isinstance(sub.value, ast.Constant) and sub.value.value is True:
					findings.append((path, sub.value.lineno, "P1", "%s() uses ignore_permissions=True: make sure "
									 "no value from the caller decides what is written" % node.name))
		elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and \
				node.func.attr in ("sql", "sql_list", "multisql") and node.args and touched(node):
			if is_string_built(node.args[0]):
				findings.append((path, node.lineno, "S1", "SQL built from strings: pass values as parameters "
								 "(frappe.db.sql(\"... %s\", (value,)))"))

	for n in sorted(lines_changed):
		if 0 < n <= len(src_lines):
			text = src_lines[n - 1]
			if SECRET_RE.search(text) and not SECRET_OK.search(text):
				findings.append((path, n, "K1", "looks like a password, token or key written in the code: "
								 "move it to settings and change it"))
	return findings


def main():
	if len(sys.argv) < 3:
		print("usage: security_check.py <base> <head>")
		return 0
	if sys.version_info < (3, 8):
		print("Security check skipped: needs Python 3.8+ on the runner (has %d.%d)." % sys.version_info[:2])
		return 1
	base, head = sys.argv[1], sys.argv[2]
	merge_base = git("merge-base", base, head).strip() or base
	findings = []
	for path, lines_changed in sorted(changed_lines(merge_base, head).items()):
		source = git("show", "%s:%s" % (head, path))
		if source:
			findings.extend(scan_file(path, lines_changed, source))
	if not findings:
		print("Security check: nothing flagged in the changed Python code.")
		return 0
	github = os.environ.get("GITHUB_ACTIONS") == "true"
	print("Security check: %d item(s) to look at (warn only, the merge is not blocked)\n" % len(findings))
	for path, line, code, msg in sorted(set(findings)):
		print("  [%s] %s:%s  %s" % (code, path, line, msg))
		if github:
			print("::warning file=%s,line=%s,title=Security check %s::%s" % (path, line, code, msg))
	print("\nWhat the codes mean: " + CODES)
	return 1


if __name__ == "__main__":
	sys.exit(main())
