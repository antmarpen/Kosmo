from datetime import datetime, timezone

from sqlalchemy import delete, func, literal, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.provider_configs.models import ProviderCandidateOperation, ProviderConfig


class ProviderConfigRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get(self, user_id: str, provider: str):
        """Personal-scope fallback: the most recently updated personal row.

        With multiple instances per owner this legacy lookup (metadata,
        read_files, untargeted verification and delete) must stay
        deterministic, so it resolves by the provisional recency rule with
        the row id as tie-breaker. Explicit flows target rows by id instead.
        """
        return await self.db.scalar(select(ProviderConfig).where(
            ProviderConfig.user_id == user_id, ProviderConfig.provider == provider,
            ProviderConfig.visibility == "personal",
        ).order_by(ProviderConfig.updated_at.desc(), ProviderConfig.id.desc()).limit(1))

    async def name_taken(self, user_id: str, provider: str, display_name: str,
                         *, exclude_id: str | None = None) -> bool:
        """Case-insensitive display-name conflict check per owner and provider."""
        query = select(ProviderConfig.id).where(
            ProviderConfig.user_id == user_id, ProviderConfig.provider == provider,
            func.lower(ProviderConfig.display_name) == func.lower(literal(display_name)),
        )
        if exclude_id is not None:
            query = query.where(ProviderConfig.id != exclude_id)
        return await self.db.scalar(query) is not None

    async def candidates(self, user_id: str, provider: str, group_ids: list[str]):
        conditions = [(ProviderConfig.visibility == "personal", ProviderConfig.user_id == user_id),
                      (ProviderConfig.visibility == "global",)]
        from sqlalchemy import and_, or_
        filters = [and_(*condition) for condition in conditions]
        if group_ids:
            filters.append(and_(ProviderConfig.visibility == "group", ProviderConfig.group_id.in_(group_ids)))
        return list((await self.db.scalars(select(ProviderConfig).where(
            ProviderConfig.provider == provider, or_(*filters)
        ))).all())

    async def memberships(self, user_id: str) -> list[str]:
        from app.domain.identity.models import GroupMembership
        return list((await self.db.scalars(select(GroupMembership.group_id).where(
            GroupMembership.user_id == user_id
        ))).all())

    async def is_member(self, user_id: str, group_id: str) -> bool:
        return group_id in await self.memberships(user_id)

    async def membership_role(self, user_id: str, group_id: str) -> str | None:
        from app.domain.identity.models import GroupMembership
        role = await self.db.scalar(select(GroupMembership.role).where(
            GroupMembership.user_id == user_id, GroupMembership.group_id == group_id
        ))
        return getattr(role, "value", role)

    async def visible(self, user_id: str, provider: str, group_ids: list[str]):
        return await self.candidates(user_id, provider, group_ids)

    async def by_id(self, config_id: str):
        return await self.db.get(ProviderConfig, config_id)

    async def delete_scoped(self, config_id: str) -> bool:
        row = await self.by_id(config_id)
        if row is None:
            return False
        await self.db.delete(row)
        await self.db.commit()
        return True

    async def create(self, user_id: str, provider: str, config_ciphertext: str, auth_ciphertext: str | None,
                     visibility: str = "personal", group_id: str | None = None,
                     verification_status: str = "unverified", *, display_name: str):
        """Insert a NEW configuration instance.

        Creating is distinct from updating: every call adds one row. The
        functional unique index (owner, provider, lower(display_name)) is the
        database-level backstop for the case-insensitive name rule; an
        `IntegrityError` from a race between the application pre-check and the
        insert is re-raised for the service to translate into a keyed
        conflict error.
        """
        row = ProviderConfig(user_id=user_id, provider=provider, visibility=visibility,
                             group_id=group_id, config_ciphertext=config_ciphertext,
                              auth_ciphertext=auth_ciphertext,
                              verification_status=verification_status, display_name=display_name,
                              format="v2")
        self.db.add(row)
        try:
            await self.db.commit()
        except IntegrityError:
            await self.db.rollback()
            raise
        await self.db.refresh(row)
        return row

    async def update(self, row: ProviderConfig, *, config_ciphertext: str, auth_ciphertext: str | None,
                     verification_status: str, display_name: str, visibility: str,
                     group_id: str | None) -> ProviderConfig:
        """Update exactly one configuration instance in place (by identity).

        Never duplicates the row: the caller passes the instance it resolved
        by id, and only the given fields change. The `updated_at` version
        marker moves so stale verification results stay guarded.

        Like `create`, a failed commit is rolled back before the
        `IntegrityError` is re-raised: two updates racing to the same
        case-insensitive name make exactly one lose at the functional unique
        index, and the loser's session must stay usable so the service can
        translate the violation into the keyed conflict error.
        """
        row.config_ciphertext = config_ciphertext
        row.auth_ciphertext = auth_ciphertext
        row.format = "v2"
        row.verification_status = verification_status
        row.display_name = display_name
        row.visibility = visibility
        row.group_id = group_id
        try:
            await self.db.commit()
        except IntegrityError:
            # The commit lost at a database constraint (for a rename race, the
            # functional unique index): discard the failed transaction so the
            # caller's session stays usable, then re-raise for the service to
            # classify. Any other exception leaves the session to the caller.
            await self.db.rollback()
            raise
        await self.db.refresh(row)
        return row

    async def set_verification_status(self, config_id: str, status: str, *,
                                      expected_updated_at=None) -> bool:
        """Update the verification status of exactly one configuration.

        When `expected_updated_at` is given, the write lands only while the
        row is unchanged since the caller read it: a verification result that
        arrives after the configuration was replaced (or deleted) must never
        brand the new files as verified, so it updates nothing.
        """
        query = update(ProviderConfig).where(ProviderConfig.id == config_id)
        if expected_updated_at is not None:
            query = query.where(ProviderConfig.updated_at == expected_updated_at)
        result = await self.db.execute(query.values(verification_status=status))
        await self.db.commit()
        return bool(result.rowcount)

    async def delete(self, user_id: str, provider: str) -> bool:
        row = await self.get(user_id, provider)
        if row is None:
            return False
        await self.db.delete(row)
        await self.db.commit()
        return True

    async def create_candidate_operation(self, user_id: str, provider: str,
                                         payload_ciphertext: str, expires_at,
                                         purpose: str = ProviderCandidateOperation.PURPOSE_DISCOVERY):
        row = ProviderCandidateOperation(user_id=user_id, provider=provider,
                                         payload_ciphertext=payload_ciphertext, expires_at=expires_at,
                                         purpose=purpose)
        self.db.add(row)
        await self.db.commit()
        await self.db.refresh(row)
        return row

    async def get_candidate_operation(self, operation_id: str):
        return await self.db.get(ProviderCandidateOperation, operation_id)

    async def delete_candidate_operation(self, operation_id: str) -> bool:
        row = await self.get_candidate_operation(operation_id)
        if row is None:
            return False
        await self.db.delete(row)
        await self.db.commit()
        return True

    async def consume_candidate_operation(self, operation_id: str, user_id: str, provider: str) -> dict | None:
        """Atomically claim a candidate operation for one container run.

        A single conditional `DELETE ... RETURNING` is the whole gate: the row
        is deleted and its payload handed over in one committed statement, so
        a concurrent second claim can never observe the row again. Returns
        `None` (claiming nothing) when the operation is missing, foreign, or
        expired — the service classifies those cases for error reporting.
        """
        return await self._claim_candidate_operation(
            operation_id, user_id, provider, require_redeemable=False)

    async def redeem_candidate_operation(self, operation_id: str, user_id: str, provider: str) -> dict | None:
        """Atomically claim a candidate operation as a verification proof.

        Same single-statement gate as consumption, further restricted to
        verification-purpose rows whose container test succeeded while the TTL
        was still live. Exactly one concurrent redemption can land; the caller
        learns whether the delete carried the row from the returned payload.
        """
        return await self._claim_candidate_operation(
            operation_id, user_id, provider, require_redeemable=True)

    async def _claim_candidate_operation(self, operation_id: str, user_id: str, provider: str,
                                         *, require_redeemable: bool) -> dict | None:
        conditions = [
            ProviderCandidateOperation.id == operation_id,
            ProviderCandidateOperation.user_id == user_id,
            ProviderCandidateOperation.provider == provider,
            ProviderCandidateOperation.expires_at > datetime.now(timezone.utc),
        ]
        if require_redeemable:
            conditions.append(ProviderCandidateOperation.purpose == ProviderCandidateOperation.PURPOSE_VERIFICATION)
            conditions.append(ProviderCandidateOperation.verification_succeeded.is_(True))
        result = await self.db.execute(
            delete(ProviderCandidateOperation)
            .where(*conditions)
            .returning(ProviderCandidateOperation.payload_ciphertext)
        )
        row = result.first()
        await self.db.commit()
        return {"payload_ciphertext": row[0]} if row else None

    async def mark_candidate_operation_verified(self, operation_id: str) -> int | None:
        """Record that the operation's container verification succeeded.

        Only a live verification-purpose operation is marked. Returns the
        seconds of validity left, or `None` when nothing was marked (missing,
        expired, or wrong purpose): such an operation can never become a proof.
        """
        result = await self.db.execute(
            update(ProviderCandidateOperation)
            .where(ProviderCandidateOperation.id == operation_id,
                   ProviderCandidateOperation.purpose == ProviderCandidateOperation.PURPOSE_VERIFICATION,
                   ProviderCandidateOperation.expires_at > datetime.now(timezone.utc))
            .values(verification_succeeded=True)
            .returning(ProviderCandidateOperation.expires_at)
        )
        row = result.first()
        await self.db.commit()
        if row is None:
            return None
        remaining = int((row[0] - datetime.now(timezone.utc)).total_seconds())
        return max(remaining, 0)

    async def purge_expired_candidate_operations(self) -> int:
        result = await self.db.execute(
            delete(ProviderCandidateOperation).where(
                ProviderCandidateOperation.expires_at <= func.now(),
            )
        )
        await self.db.commit()
        return result.rowcount
