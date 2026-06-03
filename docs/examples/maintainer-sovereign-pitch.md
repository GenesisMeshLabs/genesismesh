# Why A Maintainer Would Run A Sovereign

Open-source maintainers already carry trust decisions that are bigger than one
repository: release rights, package publishing, build approvals, security
handoffs, and emergency revocation. Genesis Mesh gives those decisions a
portable shape.

## The Maintainer Problem

Today, a maintainer's authority is usually trapped inside each platform:
GitHub team membership, package-registry permissions, CI secrets, or local
project policy. When trust changes, every downstream consumer has to learn that
change independently.

That is slow during normal rotation and dangerous during compromise.

## The Sovereign Maintainer Model

A maintainer or project can run a small sovereign that says:

- this key is Alice;
- Alice may perform `release-maintainer` actions for this project;
- this claim expires at a known time;
- this claim has been revoked.

Another project can choose to recognize that sovereign for a narrow role. A CI
gate can then accept Alice before revocation and reject the same attestation
after revocation feed import.

## Why Run One

- Preserve control of maintainer trust without giving Genesis Core the keys.
- Let downstream projects recognize your release authority without recreating
  your local access model.
- Revoke a compromised maintainer once and let recognizing projects reject the
  same portable attestation.
- Produce an auditable trust path for release decisions.

## Why This Is A Good First Wedge

Open-source maintainers are reachable without enterprise sales. The integration
is only a CI gate. The pain is concrete: release authority and revocation are
already operational responsibilities.

This does not require a global registry or marketplace. One maintainer
sovereign, one recognizing project, and one CI gate are enough to prove the
workflow.
