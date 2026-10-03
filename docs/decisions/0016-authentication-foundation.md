# ADR 0016: Authentication foundation uses Argon2id and signed JWTs

## Status

Accepted for Sprint 1.2.

## Decision

- Store passwords only as Argon2id encoded hashes using the environment-backed
  parameters in `Settings`.
- Sign JWT access and refresh tokens with an environment-provided symmetric
  `JWT_SECRET_KEY`; the supported algorithm is explicitly constrained to HS256.
- Require `sub`, `iat`, `exp`, `jti`, `token_type`, `iss`, and `aud` claims.
- Require a configured signing key of at least 32 characters before issuing or
  validating tokens. No JWT signing-key default is supplied.
- Keep token validation independent of a user table. The FastAPI dependency
  returns a validated `AuthenticatedIdentity`; later application layers may
  resolve its opaque subject against their own persistence model.
- Add no registration, login, refresh, user table, or protected product endpoint
  in this sprint.

## Rationale

Argon2id is the preferred modern password-storage algorithm and is explicitly
allowed by the build specification. Strict claim validation and a required
external signing key prevent accepting unsigned, expired, mis-issued, or
cross-audience tokens. Keeping identity resolution separate avoids coupling the
foundation to domain tables that are outside Sprint 1.2.

## Security notes

Authentication modules never log plaintext passwords, password hashes, JWT
secrets, or raw bearer credentials. Invalid credentials return generic errors.
