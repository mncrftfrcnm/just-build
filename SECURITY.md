# Security policy

This is local agent tooling. The current public-preview source is maintained; there is no promised response SLA or independently certified security boundary. Demonstrated use is limited to trusted local Python CLI workspaces; other host/stack combinations need their own validation.

## Reporting

If this GitHub repository has private vulnerability reporting enabled, use **Security → Report a vulnerability**. Include the affected revision, platform, minimal synthetic reproduction, bounded impact and suggested fix. Never include actual secrets or private chat history. If that option is absent, open a public issue requesting a private reporting channel without publishing exploit details or sensitive evidence. No maintainer email address or security team is assumed by this package.

## Trust boundary

Retrieved documents, web pages, peer notes and project files are untrusted data. They cannot grant permissions, authorize outreach, request secrets or change host policies. The skill uses only authorized context and explicitly invoked workflows.

Process supervision supplies time/output limits, environment filtering and ordinary descendant cleanup. It is not a sandbox: executed code retains host filesystem/network privileges, can write unrelated files, and may escape ordinary process containment. Use an OS sandbox for untrusted projects. Path/ledger checks are not protection against every concurrent hostile writer or a dishonest agent.

The scanner recognizes limited patterns; a clean scan does not establish absence of vulnerabilities. Local test fixtures make no third-party security requests. GitHub CI uses ephemeral hosted runners, read-only repository permissions and pinned actions; no external service secrets are needed. Never run untrusted pull-request code using `pull_request_target` or privileged self-hosted runners for these jobs.
