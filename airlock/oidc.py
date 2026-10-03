"""Operator-pinned RFC 9068 access tokens; claims never grant review scope.

The trusted issuer's public JWKS is provisioned out of band. No jku/x5u URL in
an untrusted token is fetched. Reloading the operator-owned file revokes a
subject, key, or jti immediately, including already-pending approvals.
"""
import json
from pathlib import Path
from urllib.parse import urlparse
import jwt
from pydantic import BaseModel, ConfigDict, Field
from .models import GateError


class Issuer(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    issuer: str = Field(max_length=256)
    audience: str = Field(min_length=1, max_length=256)
    additional_audiences: list[str] = Field(default_factory=list, max_length=8)
    jwks_file: str = Field(min_length=1, max_length=1024)
    subjects: dict[str, str] = Field(max_length=64)
    revoked_jti: list[str] = Field(default_factory=list, max_length=1000)
    max_token_seconds: int = Field(default=3600, ge=30, le=86400)


def configuration(path):
    raw = Path(path).read_bytes()
    if len(raw) > 65536:
        raise ValueError('identity configuration size')
    config = Issuer.model_validate_json(raw)
    if (any(not value or len(value) > 256 for value in config.additional_audiences)
            or len(set(config.additional_audiences)) != len(config.additional_audiences)
            or config.audience in config.additional_audiences):
        raise ValueError('invalid additional audience allowlist')
    origin = urlparse(config.issuer)
    if origin.scheme != 'https' or not origin.hostname or origin.username or origin.password or origin.query or origin.fragment:
        raise ValueError('HTTPS issuer required')
    if any(not sub or len(sub) > 256 or (who != 'agent:demo' and (not who.startswith('reviewer:') or who == 'reviewer:owner'))
           for sub, who in config.subjects.items()):
        raise ValueError('identity mapping must not grant operator privileges')
    keys_path = Path(config.jwks_file)
    if not keys_path.is_absolute():
        keys_path = Path(path).parent / keys_path
    raw_keys = keys_path.read_bytes()
    if len(raw_keys) > 65536:
        raise ValueError('JWKS size')
    data = json.loads(raw_keys)
    if set(data) != {'keys'} or not isinstance(data['keys'], list) or not 1 <= len(data['keys']) <= 16:
        raise ValueError('invalid JWKS')
    keys = {}
    for entry in data['keys']:
        if not isinstance(entry,dict):raise ValueError('invalid JWK object')
        kid = entry.get('kid')
        if not isinstance(kid, str) or not 1 <= len(kid) <= 128 or kid in keys:
            raise ValueError('invalid key identity')
        if entry.get('kty') != 'RSA' or entry.get('alg') != 'RS256' or entry.get('use') != 'sig' or 'd' in entry:
            raise ValueError('public RS256 signing keys required')
        key = jwt.PyJWK.from_dict(entry, algorithm='RS256').key
        if key.key_size < 2048:
            raise ValueError('undersized signing key')
        keys[kid] = key
    return config, keys


def verified_claims(token, path):
    """Validate an access token against the current operator configuration."""
    if len(token) > 8192:
        raise GateError('authentication_required', 401)
    try:
        config, keys = configuration(path)
    except (OSError, ValueError, TypeError, KeyError, jwt.PyJWTError):
        raise GateError('identity_configuration_unavailable', 503) from None
    try:
        header = jwt.get_unverified_header(token)
        if header.get('typ') not in {'at+jwt', 'application/at+jwt'} or header.get('alg') != 'RS256':
            raise ValueError('access token profile required')
        if any(k in header for k in ('jku', 'x5u', 'jwk', 'crit')):
            raise ValueError('untrusted key reference')
        key = keys[header['kid']]
        claims = jwt.decode(token, key, algorithms=['RS256'], issuer=config.issuer, audience=config.audience,
                            options={'require': ['iss', 'aud', 'sub', 'exp', 'iat', 'jti', 'client_id'],
                                     'strict_aud': not config.additional_audiences})
        audience = claims['aud']
        if isinstance(audience, list):
            if (not config.additional_audiences or not audience
                    or not all(isinstance(value, str) for value in audience)
                    or len(set(audience)) != len(audience)
                    or config.audience not in audience
                    or not set(audience) <= {config.audience, *config.additional_audiences}):
                raise ValueError('unapproved token audience')
        elif audience != config.audience:
            raise ValueError('unapproved token audience')
        # PyJWT validates temporal order against now; also prohibit coercion,
        # unbounded lifetimes and empty/revoked identifiers.
        if any(type(claims[k]) is not int for k in ('iat', 'exp')):
            raise ValueError('invalid token timestamps')
        if not 0 < claims['exp'] - claims['iat'] <= config.max_token_seconds:
            raise ValueError('invalid token lifetime')
        if not all(isinstance(claims[k], str) and 0 < len(claims[k]) <= 256 for k in ('sub', 'jti', 'client_id')):
            raise ValueError('invalid token identifier')
        if claims['jti'] in config.revoked_jti:
            raise ValueError('revoked token')
        return claims, config.subjects.get(claims['sub'])
    except (ValueError, TypeError, KeyError, jwt.PyJWTError):
        raise GateError('authentication_required', 401) from None


def identify(token, path):
    if not path or token.count('.') != 2:
        return None
    return verified_claims(token, path)[1]
