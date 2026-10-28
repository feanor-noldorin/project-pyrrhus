# Security policy

This project is a work-in-progress PC port with no release yet. Security fixes go to the latest `main`; there are no release branches.

## Reporting a vulnerability

Please report privately through GitHub's **"Report a vulnerability"** button on this repository's Security tab
(private vulnerability reporting). Do not open a public issue for a security problem. Include what is affected
(file, function or build step), how to reproduce it, and the impact you expect. You should get a first answer within
a week.

## Scope

- In scope: the port's own code and tools in this repository (for example the archive and save-data parsers, the
  file-system layer and the first-run and packaging scripts).
- Out of scope: Killzone 2 itself, the PlayStation 3 system software, and third-party projects (report those to
  their maintainers; recompiler issues to [ps3recomp](https://github.com/sp00nznet/ps3recomp)).
- Any online feature will only ever talk to a server the player chooses; anything that lets a server or another player
  run code or read files on a player's machine is a vulnerability.
