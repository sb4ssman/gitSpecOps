# Security policy

gitSpecOps decides what may leave your machines, so a flaw in it matters. Thank you for
reporting one privately.

## Reporting a vulnerability

Use GitHub's private reporting: the **Security** tab of this repository, then **Report a
vulnerability**. Please do not open a public issue, pull request or discussion that describes the
problem, and do not include a real secret in the report; a made-up example that reproduces it is
enough.

Say what you did, what happened, what you expected, and which system and Python version you used.
This is a one-person project: expect an acknowledgement within a week, and a fix or an honest
assessment after that. Reporters are credited in the fix unless they ask not to be.

## What counts

Anything that breaks a promise in the [README](README.md), especially:

- a `secure-commit`, `secure-push` or publish that goes through when its security checks should
  hold it, or a scan that reports "passed" when something was not checked (Basic `commit` and
  `push` are plain Git operations and do not check, by design);
- a protected value, finding, local path, file content or the fleet key leaving this machine, in
  a status file, a log, a report or the web view;
- the local web view or the Tailscale listener accepting a request from anyone it should refuse;
- a repository changed without the person's approval, or a destructive Git operation run at all;
- credentials read, stored or forwarded.

Out of scope: what an optional scanner (Gitleaks, Betterleaks, TruffleHog) does or misses on its
own, and anything that needs an attacker who already controls your account or your machine.

## Supported versions

gitSpecOps is a development preview. Only the latest commit on `main` is supported; fixes are not
backported to tags.
