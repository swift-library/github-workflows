"""Read the maintenance declaration and compare GitHub metadata using GET only."""

from copy import deepcopy
import json
from pathlib import Path
import re
import subprocess


ROOT = Path(__file__).resolve().parents[1]
MISSING = object()


class Unavailable(ValueError):
    """An observation could not be obtained; it is not evidence of conformance."""


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate declaration key: {key}")
        result[key] = value
    return result


def load_declaration(root=ROOT):
    text = (root / "MAINTENANCE.md").read_text(encoding="utf-8")
    blocks = re.findall(r"<!-- settings-declaration -->\s*```json\n(.*?)\n```", text, re.S)
    if len(blocks) != 1:
        raise ValueError("MAINTENANCE.md must contain one settings-declaration JSON block")
    value = json.loads(blocks[0], object_pairs_hook=unique_object)
    validate_declaration(value)
    return value


def validate_declaration(value):
    if not isinstance(value, dict) or value.get("schema") != 1:
        raise ValueError("unsupported settings declaration schema")
    defaults = value.get("defaults", {})
    if not isinstance(defaults, dict):
        raise ValueError("defaults must be an object")
    required = {
        "repository": {"allow_squash_merge", "allow_merge_commit", "allow_rebase_merge",
                       "delete_branch_on_merge", "squash_merge_commit_title", "squash_merge_commit_message"},
        "workflow_token": {"default_workflow_permissions", "can_approve_pull_request_reviews"},
        "private_vulnerability_reporting": {"enabled"},
        "branch_ruleset": {"name", "target", "enforcement", "bypass_actors", "conditions", "rules"},
        "tag_ruleset": {"name", "target", "enforcement", "bypass_actors", "rules"},
        "status_checks": {"integration_id", "strict_required_status_checks_policy"},
    }
    for key, fields in required.items():
        if not isinstance(defaults.get(key), dict) or not fields <= defaults[key].keys():
            raise ValueError(f"incomplete defaults.{key}")
    for section, fields in {
        "repository": {"allow_squash_merge": bool, "allow_merge_commit": bool, "allow_rebase_merge": bool,
                       "delete_branch_on_merge": bool, "squash_merge_commit_title": str,
                       "squash_merge_commit_message": str},
        "workflow_token": {"default_workflow_permissions": str, "can_approve_pull_request_reviews": bool},
        "private_vulnerability_reporting": {"enabled": bool},
        "status_checks": {"integration_id": int, "strict_required_status_checks_policy": bool},
    }.items():
        for key, expected_type in fields.items():
            if type(defaults[section][key]) is not expected_type:
                raise ValueError(f"invalid defaults.{section}.{key} type")
    for kind in ("branch_ruleset", "tag_ruleset"):
        rules = defaults[kind]["rules"]
        if not isinstance(rules, list) or not rules or any(
            not isinstance(rule, dict) or not isinstance(rule.get("type"), str) for rule in rules
        ) or len({rule["type"] for rule in rules}) != len(rules):
            raise ValueError(f"invalid defaults.{kind}.rules")
    repositories = value.get("repositories")
    if not isinstance(repositories, dict) or not repositories:
        raise ValueError("repositories must be a nonempty mapping")
    for name, member in repositories.items():
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", name) or not isinstance(member, dict):
            raise ValueError("invalid repository declaration")
        for key in ("default_branch", "description"):
            if not isinstance(member.get(key), str) or not member[key].strip():
                raise ValueError(f"{name}.{key} must be nonempty text")
        for key in ("topics", "required_checks", "release_tag_patterns"):
            items = member.get(key)
            if not isinstance(items, list) or any(not isinstance(item, str) or not item for item in items):
                raise ValueError(f"{name}.{key} must be a list of strings")
            if len(set(items)) != len(items) or (key == "required_checks" and not items):
                raise ValueError(f"{name}.{key} must be unique and required checks cannot be empty")
        if any(not pattern.startswith("refs/tags/") for pattern in member["release_tag_patterns"]):
            raise ValueError(f"{name}: tag patterns must include refs/tags/")
        if member.get("visibility", "public") not in {"public", "private"}:
            raise ValueError(f"{name}.visibility must be public or private")
        if "enforcement_gap" in member and (
                member.get("visibility") != "private" or not isinstance(member["enforcement_gap"], str)
                or not member["enforcement_gap"].strip()):
            raise ValueError(f"{name}.enforcement_gap must be nonempty text on a private repository")


def api(path, *, paginate=False):
    command = ["gh", "api", "--method", "GET", path,
               "-H", "Accept: application/vnd.github+json"]
    if paginate:
        command += ["--paginate", "--slurp"]
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False, timeout=120)
    except (OSError, subprocess.SubprocessError):
        raise Unavailable(f"GET {path}: request unavailable") from None
    if result.returncode:
        # Never echo diagnostic bodies or authentication material.
        try:
            status = json.loads(result.stdout).get("status", "unavailable")
        except (ValueError, AttributeError):
            status = "unavailable"
        if str(status) not in {"401", "403", "404", "429"}:
            status = "unavailable"
        raise Unavailable(f"GET {path}: HTTP {status}")
    try:
        return json.loads(result.stdout)
    except ValueError:
        raise Unavailable(f"GET {path}: invalid JSON") from None


def collection(path, get=api):
    pages = get(path, paginate=True)
    if not isinstance(pages, list) or any(not isinstance(page, list) for page in pages):
        raise Unavailable(f"GET {path}: invalid paginated collection")
    return [item for page in pages for item in page]


def compare(path, expected, observed):
    if observed is MISSING:
        return [f"UNKNOWN {path}: field unavailable"]
    if isinstance(expected, dict):
        if not isinstance(observed, dict):
            return [f"UNKNOWN {path}: expected an object response"]
        return [finding for key, value in expected.items()
                for finding in compare(path + "." + key, value, observed.get(key, MISSING))]
    if type(expected) is not type(observed) or expected != observed:
        return [f"DRIFT {path}: expected {json.dumps(expected, ensure_ascii=False)}; "
                f"observed {json.dumps(observed, ensure_ascii=False)}"]
    return []


def expected_rulesets(declaration, member):
    defaults = declaration["defaults"]
    branch = deepcopy(defaults["branch_ruleset"])
    checks = deepcopy(defaults["status_checks"])
    app = checks.pop("integration_id")
    checks["required_status_checks"] = [
        {"context": name, "integration_id": app} for name in sorted(member["required_checks"])
    ]
    branch["rules"].append({"type": "required_status_checks", "parameters": checks})
    rulesets = [branch]
    if member["release_tag_patterns"]:
        tags = deepcopy(defaults["tag_ruleset"])
        tags["conditions"] = {"ref_name": {"include": member["release_tag_patterns"], "exclude": []}}
        rulesets.append(tags)
    return rulesets


def canonical(value):
    """Rules, actors, patterns, checks and topics are sets in this projection."""
    if isinstance(value, dict):
        return {key: canonical(item) for key, item in value.items()}
    if isinstance(value, list):
        return sorted((canonical(item) for item in value), key=lambda item: json.dumps(item, sort_keys=True))
    return value


def compare_ruleset(path, expected, observed):
    findings = compare(path, {key: canonical(value) for key, value in expected.items() if key != "rules"},
                       canonical(observed))
    rules = observed.get("rules")
    if not isinstance(rules, list) or any(not isinstance(rule, dict) or not isinstance(rule.get("type"), str)
                                        for rule in rules):
        return findings + [f"UNKNOWN {path}.rules: rules unavailable"]
    expected_types = sorted(rule["type"] for rule in expected["rules"])
    findings += compare(path + ".rule_types", expected_types, sorted(rule["type"] for rule in rules))
    for expected_rule in expected["rules"]:
        matches = [rule for rule in rules if rule["type"] == expected_rule["type"]]
        if len(matches) == 1:
            findings += compare(path + "." + expected_rule["type"], canonical(expected_rule), canonical(matches[0]))
    return findings


def check_repository(name, member, declaration, get=api):
    prefix = "repos/" + name
    defaults = declaration["defaults"]
    findings = []
    visibility = member.get("visibility", "public")
    projections = [
        ("repository", prefix, {**defaults["repository"], **{
            key: member[key] for key in ("default_branch", "description", "topics")},
            "visibility": visibility}),
        ("workflow_token", prefix + "/actions/permissions/workflow", defaults["workflow_token"]),
    ]
    # Private vulnerability reporting exists only for public repositories.
    if visibility == "public":
        projections.append(("private_vulnerability_reporting", prefix + "/private-vulnerability-reporting",
                            defaults["private_vulnerability_reporting"]))
    for label, endpoint, expected in projections:
        try:
            findings += compare(name + "." + label, canonical(expected), canonical(get(endpoint)))
        except Unavailable as error:
            findings.append(f"UNKNOWN {name}.{label}: {error}")
    if "enforcement_gap" in member:
        # A declared plan limitation is an explicit acceptance gap, never a passing setting.
        return findings + [f"GAP {name}.rulesets: {member['enforcement_gap']}"]
    try:
        summaries = collection(prefix + "/rulesets?includes_parents=true&per_page=100", get)
        if any(not isinstance(item, dict) or not isinstance(item.get("id"), int) for item in summaries):
            raise Unavailable("invalid ruleset inventory")
        rulesets = []
        for summary in summaries:
            ruleset = get(prefix + f"/rulesets/{summary['id']}?includes_parents=true")
            if not isinstance(ruleset, dict) or not isinstance(ruleset.get("name"), str):
                raise Unavailable("invalid full ruleset response")
            rulesets.append(ruleset)
        expected = expected_rulesets(declaration, member)
        findings += compare(name + ".rulesets", sorted(item["name"] for item in expected),
                            sorted(item["name"] for item in rulesets))
        for rule in expected:
            matches = [item for item in rulesets if item["name"] == rule["name"]]
            if len(matches) == 1:
                findings += compare_ruleset(name + ".rulesets." + rule["name"], rule, matches[0])
    except Unavailable as error:
        findings.append(f"UNKNOWN {name}.rulesets: {error}")
    return findings or [f"PASS {name} settings"]


def check_online(declaration, get=api):
    results = []
    organizations = sorted({name.split("/")[0] for name in declaration["repositories"]})
    for organization in organizations:
        try:
            inventory = collection(f"orgs/{organization}/repos?type=public&per_page=100", get)
            if any(not isinstance(item, dict) or not isinstance(item.get("full_name"), str)
                   or not isinstance(item.get("private"), bool)
                   or not isinstance(item.get("archived"), bool) for item in inventory):
                raise Unavailable("invalid repository inventory")
            expected = sorted(name for name, member in declaration["repositories"].items()
                              if name.startswith(organization + "/")
                              and member.get("visibility", "public") == "public")
            observed = sorted(item["full_name"] for item in inventory if not item["private"] and not item["archived"])
            results += compare(organization + ".public_members", expected, observed)
        except Unavailable as error:
            results.append(f"UNKNOWN {organization}.public_members: {error}")
    # A failed endpoint in one repository does not hide drift in another.
    for name, member in declaration["repositories"].items():
        results.extend(check_repository(name, member, declaration, get))
    return results
