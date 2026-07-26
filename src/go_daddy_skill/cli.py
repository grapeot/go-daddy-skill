from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import requests

from .authority import AuthorityError, require_matching_authority, resolve_nameservers
from .client import SCHEMA, GoDaddyAPIError, GoDaddyClient, GoDaddyProtocolError
from .plan import (
    build_dns_create_plan,
    record_confirmation,
    records_are_identical,
    validate_dns_create_plan,
)
from .write_client import GoDaddyDNSWriteClient


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="go-daddy-skill",
        description="Read-first GoDaddy inventory with guarded, dry-run-first DNS creation.",
    )
    parser.add_argument("--pretty", action="store_true", help="Indent JSON output")
    commands = parser.add_subparsers(dest="command", required=True)

    auth = commands.add_parser("auth", help="Credential diagnostics")
    auth_commands = auth.add_subparsers(dest="auth_command", required=True)
    auth_status = auth_commands.add_parser("status", help="Report credential presence")
    auth_status.add_argument("--live", action="store_true", help="Make a minimal read request")

    domains = commands.add_parser("domains", help="Domain inventory")
    domain_commands = domains.add_subparsers(dest="domain_command", required=True)
    domain_list = domain_commands.add_parser("list", help="List all account-visible domains")
    domain_list.add_argument("--page-size", type=int, default=1000)
    domain_list.add_argument("--start-marker")
    domain_list.add_argument("--max-items", type=int)
    domain_get = domain_commands.add_parser("get", help="Get privacy-minimized domain detail")
    domain_get.add_argument("domain")

    dns = commands.add_parser("dns", help="GoDaddy-hosted DNS records")
    dns_commands = dns.add_subparsers(dest="dns_command", required=True)
    dns_list = dns_commands.add_parser("list", help="List all records in a GoDaddy zone")
    dns_list.add_argument("domain")
    dns_list.add_argument("--type", dest="record_type")
    dns_list.add_argument("--name")
    dns_list.add_argument("--page-size", type=int, default=100)
    dns_list.add_argument("--max-items", type=int)
    dns_create = dns_commands.add_parser("create", help="Plan or execute a DNS record create")
    dns_create_commands = dns_create.add_subparsers(dest="dns_create_command", required=True)
    create_plan = dns_create_commands.add_parser(
        "plan", help="Dry-run and create an immutable DNS write plan"
    )
    create_plan.add_argument("domain")
    create_plan.add_argument("--type", dest="record_type", required=True)
    create_plan.add_argument("--name", required=True)
    create_plan.add_argument("--data", required=True)
    create_plan.add_argument("--ttl", type=int, default=600)
    create_plan.add_argument("--priority", type=int)
    create_plan.add_argument("--weight", type=int)
    create_plan.add_argument("--port", type=int)
    create_plan.add_argument("--service")
    create_plan.add_argument("--protocol")
    create_plan.add_argument("--output", required=True)
    create_apply = dns_create_commands.add_parser(
        "apply", help="Revalidate a plan; only --execute performs the write"
    )
    create_apply.add_argument("plan")
    create_apply.add_argument("--confirm-domain", required=True)
    create_apply.add_argument(
        "--confirm-record",
        help="Exact required_confirm_record from a non-TXT dry-run",
    )
    create_apply.add_argument(
        "--execute",
        action="store_true",
        help="Perform the one-shot create after explicit user authorization",
    )
    return parser


def _dump(value: dict[str, Any], *, pretty: bool, stream: Any | None = None) -> None:
    stream = stream or sys.stdout
    print(
        json.dumps(value, indent=2 if pretty else None, separators=None if pretty else (",", ":")),
        file=stream,
    )


def _success(
    command: str,
    data: dict[str, Any],
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "ok": True,
        "command": command,
        "data": data,
        "meta": meta or {"complete": True},
    }


def _error(command: str, kind: str, message: str, **details: Any) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "ok": False,
        "command": command,
        "error": {"kind": kind, "message": message, **details},
        "meta": {"complete": False},
    }


def _command_name(args: argparse.Namespace) -> str:
    suffix = (
        getattr(args, "auth_command", None)
        or getattr(args, "domain_command", None)
        or getattr(args, "dns_command", None)
    )
    nested = getattr(args, "dns_create_command", None)
    parts = [args.command, suffix, nested]
    return ".".join(part for part in parts if part)


def _domain_nameservers(detail: dict[str, Any]) -> list[str]:
    values = detail.get("nameServers")
    if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
        raise GoDaddyProtocolError("GoDaddy domain detail did not include nameservers")
    return values


def _record_from_plan_args(args: argparse.Namespace) -> dict[str, Any]:
    record: dict[str, Any] = {
        "type": args.record_type,
        "name": args.name,
        "data": args.data,
        "ttl": args.ttl,
    }
    for field in ("priority", "weight", "port", "service", "protocol"):
        value = getattr(args, field)
        if value is not None:
            record[field] = value
    return record


def _identical_record_exists(
    records: list[dict[str, Any]], target: dict[str, Any]
) -> bool:
    return any(records_are_identical(record, target) for record in records)


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    command = _command_name(args)
    token = os.environ.get("GODADDY_PAT", "")
    write_token = os.environ.get("GODADDY_WRITE_PAT", "")
    execute = command == "dns.create.apply" and args.execute
    active_token = write_token if execute else token

    try:
        if execute and (
            not write_token.strip()
            or any(character.isspace() for character in write_token)
            or ":" in write_token
        ):
            raise ValueError("GODADDY_WRITE_PAT is missing or malformed")
        client = GoDaddyClient(active_token)
        if command == "auth.status":
            result = _success(command, client.auth_status(live=args.live))
        elif command == "domains.list":
            domains, meta = client.list_domains(
                page_size=args.page_size,
                start_marker=args.start_marker,
                max_items=args.max_items,
            )
            result = _success(command, {"domains": domains}, meta)
        elif command == "domains.get":
            result = _success(command, {"domain": client.get_domain(args.domain)})
        elif command == "dns.list":
            records, meta = client.list_dns_records(
                args.domain,
                record_type=args.record_type,
                name=args.name,
                page_size=args.page_size,
                max_items=args.max_items,
            )
            result = _success(command, {"domain": args.domain, "records": records}, meta)
        elif command == "dns.create.plan":
            detail = client.get_domain(args.domain)
            require_matching_authority(
                _domain_nameservers(detail), resolve_nameservers(args.domain)
            )
            existing, meta = client.list_dns_records(
                args.domain,
                record_type=args.record_type.upper(),
                name=args.name,
            )
            if not meta["complete"]:
                raise GoDaddyProtocolError("Existing DNS record inventory is incomplete")
            plan = build_dns_create_plan(
                args.domain,
                _record_from_plan_args(args),
                existing_records=existing,
            )
            output = Path(args.output)
            try:
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
            except OSError as exc:
                raise ValueError(f"Unable to write DNS plan: {exc}") from exc
            result = _success(
                command,
                {
                    "dry_run": True,
                    "would_create": plan["record"],
                    "authorization": plan["authorization"],
                    "plan": plan,
                    "output": str(output),
                },
                {"complete": True, "requests": client.request_count},
            )
        elif command == "dns.create.apply":
            plan_path = Path(args.plan)
            try:
                plan_document = json.loads(plan_path.read_text(encoding="utf-8"))
            except OSError as exc:
                raise ValueError(f"Unable to read DNS plan: {exc}") from exc
            plan = validate_dns_create_plan(
                plan_document,
                confirm_domain=args.confirm_domain,
            )
            if args.execute and plan["record"]["type"] != "TXT":
                required = record_confirmation(plan["record"])
                if args.confirm_record != required:
                    raise ValueError(
                        "Non-TXT execution requires the exact required_confirm_record "
                        "value from the dry-run"
                    )
            detail = client.get_domain(plan["zone"])
            require_matching_authority(
                _domain_nameservers(detail), resolve_nameservers(plan["zone"])
            )
            existing, meta = client.list_dns_records(
                plan["zone"],
                record_type=plan["record"]["type"],
                name=plan["record"]["name"],
            )
            if not meta["complete"]:
                raise GoDaddyProtocolError("Pre-apply DNS record inventory is incomplete")
            if _identical_record_exists(existing, plan["record"]):
                raise ValueError("An identical DNS record appeared after planning")
            if not args.execute:
                result = _success(
                    command,
                    {
                        "dry_run": True,
                        "ready_to_execute": True,
                        "would_create": plan["record"],
                        "authorization": plan["authorization"],
                        "instruction": (
                            "No DNS mutation was performed. Obtain explicit user authorization "
                            "for this exact record, then rerun this apply command with --execute."
                        ),
                    },
                    {"complete": True, "plan_digest": plan["digest"]},
                )
                _dump(result, pretty=args.pretty)
                return 0
            created = GoDaddyDNSWriteClient(write_token).create_record(
                plan["zone"], plan["record"]
            )
            verified, verify_meta = client.list_dns_records(
                plan["zone"],
                record_type=plan["record"]["type"],
                name=plan["record"]["name"],
            )
            record_id = created["record"]["recordId"]
            matched = any(record.get("recordId") == record_id for record in verified)
            if not verify_meta["complete"] or not matched:
                raise GoDaddyProtocolError(
                    "DNS record was created but post-write API verification failed"
                )
            result = _success(
                command,
                {
                    "created": created["record"],
                    "verified": True,
                    "cleanup": {
                        "zone": plan["zone"],
                        "record_id": record_id,
                        "instruction": "Delete this record manually after verification.",
                    },
                },
                {"complete": True, "plan_digest": plan["digest"]},
            )
        else:
            parser.error(f"Unsupported command: {command}")
            return 2
    except ValueError as exc:
        credential_error = (
            not active_token.strip()
            or any(character.isspace() for character in active_token)
            or ":" in active_token
        )
        kind = "authentication" if credential_error else "input"
        _dump(
            _error(command, kind, str(exc)),
            pretty=args.pretty,
            stream=sys.stderr,
        )
        return 3 if credential_error else 2
    except GoDaddyAPIError as exc:
        if exc.status_code == 401:
            kind = "authentication"
        elif exc.status_code == 403:
            kind = "authorization"
        else:
            kind = "provider_http"
        _dump(
            _error(
                command,
                kind,
                str(exc),
                request={
                    "method": exc.method,
                    "path": exc.path,
                    "request_id": exc.request_id,
                },
                response={
                    "status": exc.status_code,
                    "headers": exc.response_headers,
                    "body": exc.response_body,
                },
            ),
            pretty=args.pretty,
            stream=sys.stderr,
        )
        return 3 if exc.status_code == 401 else 4 if exc.status_code == 403 else 5
    except requests.RequestException as exc:
        _dump(_error(command, "network", str(exc)), pretty=args.pretty, stream=sys.stderr)
        return 5
    except (AuthorityError, GoDaddyProtocolError) as exc:
        _dump(_error(command, "protocol", str(exc)), pretty=args.pretty, stream=sys.stderr)
        return 7

    _dump(result, pretty=args.pretty)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
