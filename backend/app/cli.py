"""Explicit administrative bootstrap commands; no operator account is seeded by default."""

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
from typing import Any

from pydantic import EmailStr, TypeAdapter, ValidationError
from sqlalchemy import select

from app.core.config import Settings, get_settings
from app.core.security import hash_password
from app.db.base import Base
from app.db.session import build_engine, build_session_factory
from app.models import User
from app.models.entities import UserRole
from app.schemas.auth import RegisterRequest


class OperatorCommandError(ValueError):
    pass


async def create_operator(
    settings: Settings,
    *,
    email: str,
    role: str,
    full_name: str | None = None,
    password: str | None = None,
    promote_existing: bool = False,
) -> dict[str, Any]:
    if role not in {UserRole.ANALYST.value, UserRole.ADMIN.value}:
        raise OperatorCommandError("role debe ser analyst o admin")
    try:
        normalized_email = str(TypeAdapter(EmailStr).validate_python(email)).lower()
    except ValidationError as exc:
        raise OperatorCommandError("email no es válido") from exc

    engine = build_engine(settings)
    factory = build_session_factory(engine)
    try:
        if settings.auto_create_tables:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
        async with factory() as session:
            user = await session.scalar(select(User).where(User.email == normalized_email))
            if user is not None:
                if not user.is_active:
                    raise OperatorCommandError("la cuenta existe pero está inactiva")
                if user.role == role:
                    return {
                        "status": "unchanged",
                        "email": user.email,
                        "role": user.role,
                        "created": False,
                    }
                if not promote_existing:
                    raise OperatorCommandError(
                        "la cuenta ya existe; use --promote-existing para cambiar su rol"
                    )
                user.role = role
                await session.commit()
                return {
                    "status": "promoted",
                    "email": user.email,
                    "role": user.role,
                    "created": False,
                }

            if full_name is None or password is None:
                raise OperatorCommandError(
                    "una cuenta nueva requiere --full-name y contraseña interactiva"
                )
            try:
                registration = RegisterRequest(
                    email=normalized_email,
                    full_name=full_name,
                    password=password,
                )
            except ValidationError as exc:
                raise OperatorCommandError(str(exc)) from exc
            user = User(
                email=normalized_email,
                full_name=registration.full_name.strip(),
                password_hash=hash_password(registration.password),
                role=role,
                preferences={},
            )
            session.add(user)
            await session.commit()
            return {
                "status": "created",
                "email": user.email,
                "role": user.role,
                "created": True,
            }
    finally:
        await engine.dispose()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Administración segura de PRORA")
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser(
        "create-operator",
        help="Crea el primer operador o promueve explícitamente una cuenta registrada",
    )
    create.add_argument("--email", required=True)
    create.add_argument("--role", required=True, choices=["analyst", "admin"])
    create.add_argument("--full-name")
    create.add_argument(
        "--promote-existing",
        action="store_true",
        help="Autoriza el cambio de rol de una cuenta existente",
    )
    return parser


def main() -> None:
    arguments = _parser().parse_args()
    password = None
    if arguments.command == "create-operator" and arguments.full_name:
        password = getpass.getpass("Contraseña (no se mostrará): ")
        confirmation = getpass.getpass("Repita la contraseña: ")
        if password != confirmation:
            raise SystemExit("Las contraseñas no coinciden")
    try:
        result = asyncio.run(
            create_operator(
                get_settings(),
                email=arguments.email,
                role=arguments.role,
                full_name=arguments.full_name,
                password=password,
                promote_existing=arguments.promote_existing,
            )
        )
    except OperatorCommandError as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
