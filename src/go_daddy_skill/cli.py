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
from .plan import build_txt_create_plan, validate_txt_create_plan
from .write_client import GoDaddyDNSWriteClient


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="go-daddy-skill",
        description="Read-first GoDaddy inventory with guarded DNS TXT creation.",
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
    dns_create = dns_commands.add_parser("create", help="Plan or apply a TXT record create")
    dns_create_commands = dns_create.add_subparsers(dest="dns_create_command", required=True)
    create_plan = dns_create_commands.add_parser("plan", help="Create an immutable TXT write plan")
    create_plan.add_argument("domain")
    create_plan.add_argument("--name", required=True)
    create_plan.add_argument("--data", required=True)
    create_plan.add_argument("--ttl", type=int, default=600)
    create_plan.add_argument("--output", required=True)
    create_apply = dns_create_commands.add_parser(
        "apply", help="Apply one unexpired TXT write plan"
    )
    create_apply.add_argument("plan")
    create_apply.add_argument("--confirm-domain", required=True)
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


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    command = _command_name(args)
    token = os.environ.get("GODADDY_PAT", "")
    write_token = os.environ.get("GODADDY_WRITE_PAT", "")
    active_token = write_token if command == "dns.create.apply" else token

    try:
        if command == "dns.create.apply" and (
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
                record_type="TXT",
                name=args.name,
            )
            if not meta["complete"]:
                raise GoDaddyProtocolError("Existing TXT record inventory is incomplete")
            plan = build_txt_create_plan(
                args.domain,
                args.name,
                args.data,
                args.ttl,
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
                {"plan": plan, "output": str(output)},
                {"complete": True, "requests": client.request_count},
            )
        elif command == "dns.create.apply":
            plan_path = Path(args.plan)
            try:
                plan_document = json.loads(plan_path.read_text(encoding="utf-8"))
            except OSError as exc:
                raise ValueError(f"Unable to read DNS plan: {exc}") from exc
            plan = validate_txt_create_plan(
                plan_document,
                confirm_domain=args.confirm_domain,
            )
            detail = client.get_domain(plan["zone"])
            require_matching_authority(
                _domain_nameservers(detail), resolve_nameservers(plan["zone"])
            )
            existing, meta = client.list_dns_records(
                plan["zone"],
                record_type="TXT",
                name=plan["record"]["name"],
            )
            if not meta["complete"]:
                raise GoDaddyProtocolError("Pre-apply TXT record inventory is incomplete")
            if any(
                str(record.get("type", "")).upper() == "TXT"
                and str(record.get("name", "")).lower()
                == plan["record"]["name"].lower()
                and record.get("data") == plan["record"]["data"]
                for record in existing
            ):
                raise ValueError("An identical TXT record appeared after planning")
            created = GoDaddyDNSWriteClient(write_token).create_txt_record(
                plan["zone"], plan["record"]
            )
            verified, verify_meta = client.list_dns_records(
                plan["zone"],
                record_type="TXT",
                name=plan["record"]["name"],
            )
            record_id = created["record"]["recordId"]
            matched = any(record.get("recordId") == record_id for record in verified)
            if not verify_meta["complete"] or not matched:
                raise GoDaddyProtocolError(
                    "TXT record was created but post-write API verification failed"
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
