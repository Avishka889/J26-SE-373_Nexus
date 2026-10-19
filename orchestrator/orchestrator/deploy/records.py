"""Rows from the deployment tables, as the contract types that describe them."""

from sdlc_contracts import VerifiedRelease

from ..db import store


def verified_release(row: store.Row) -> VerifiedRelease:
    """A verified deployment row, as the release a rollback would restore.

    The per target facts a restore needs (the image digest, the commit, the
    providers' own deployment ids) travel in the row's fingerprint, written by
    the saga when it verified the release.
    """
    fingerprint = row.get("fingerprint") or {}
    return VerifiedRelease(
        deployment_id=str(row["id"]),
        deploy_version=row["deploy_version"],
        candidate_hash=row["candidate_hash"],
        lockfile_sha256=fingerprint.get("lockfileSha256"),
        target=row["target"],
        image_digest=fingerprint.get("imageDigest"),
        commit_sha=fingerprint.get("commitSha"),
        render_deploy_id=fingerprint.get("renderDeployId"),
        vercel_deployment_id=fingerprint.get("vercelDeploymentId"),
        url=row.get("url"),
        verified_at=row["verified_at"] or row["created_at"],
    )
