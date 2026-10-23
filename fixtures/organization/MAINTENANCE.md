# Organization fixture

| Repository | Checks | Tags |
| --- | --- | --- |
| `example-org/.github` | `policy / policy`, `check` | `v*` |
| `example-org/core` | `policy / policy`, `validate / swift-package`, `presentation / presentation` | `[0-9]*.[0-9]*.[0-9]*` |
| `example-org/cli` | `policy / policy`, `validate / swift-package`, `smoke`, `presentation / presentation` | `[0-9]*.[0-9]*.[0-9]*` |
| `example-org/homebrew-tap` | `policy / policy`, `homebrew`, `presentation / presentation` | None |
| `example-org/agents-tools.github.io` | `policy / policy`, `site` | None |
| `example-org/.github-private` | `policy / policy`, `check / profile` | None |

<!-- settings-declaration -->
```json
{
  "schema": 1,
  "defaults": {
    "repository": {
      "allow_squash_merge": true,
      "allow_merge_commit": false,
      "allow_rebase_merge": false,
      "delete_branch_on_merge": true,
      "squash_merge_commit_title": "PR_TITLE",
      "squash_merge_commit_message": "BLANK"
    },
    "workflow_token": {
      "default_workflow_permissions": "read",
      "can_approve_pull_request_reviews": false
    },
    "private_vulnerability_reporting": {
      "enabled": true
    },
    "branch_ruleset": {
      "name": "Default branch",
      "target": "branch",
      "enforcement": "active",
      "bypass_actors": [],
      "conditions": {
        "ref_name": {
          "include": [
            "~DEFAULT_BRANCH"
          ],
          "exclude": []
        }
      },
      "rules": [
        {
          "type": "deletion"
        },
        {
          "type": "non_fast_forward"
        },
        {
          "type": "required_signatures"
        },
        {
          "type": "pull_request",
          "parameters": {
            "allowed_merge_methods": [
              "squash"
            ],
            "required_approving_review_count": 0,
            "dismiss_stale_reviews_on_push": false,
            "require_code_owner_review": false,
            "require_last_push_approval": false,
            "required_review_thread_resolution": true
          }
        }
      ]
    },
    "status_checks": {
      "integration_id": 15368,
      "strict_required_status_checks_policy": false,
      "do_not_enforce_on_create": false
    },
    "tag_ruleset": {
      "name": "Release tags",
      "target": "tag",
      "enforcement": "active",
      "bypass_actors": [],
      "rules": [
        {
          "type": "update"
        },
        {
          "type": "deletion"
        }
      ]
    }
  },
  "repositories": {
    "example-org/.github": {
      "default_branch": "master",
      "description": "Organization profile, brand and shared standards for agents-tools.",
      "topics": [],
      "required_checks": [
        "policy / policy",
        "check"
      ],
      "release_tag_patterns": [
        "refs/tags/v*"
      ]
    },
    "example-org/core": {
      "default_branch": "master",
      "description": "Swift libraries behind agents and skill: sources, locks, skills, instructions and watch.",
      "topics": [
        "agent-skills",
        "agents-md",
        "ai-agents",
        "swift",
        "swift-package"
      ],
      "required_checks": [
        "policy / policy",
        "validate / swift-package",
        "presentation / presentation"
      ],
      "release_tag_patterns": [
        "refs/tags/[0-9]*.[0-9]*.[0-9]*"
      ]
    },
    "example-org/cli": {
      "default_branch": "master",
      "description": "Install and update agent skills and instructions, resolved to exact versions.",
      "topics": [
        "agent-skills",
        "agents-md",
        "ai-agents",
        "claude-code",
        "cli",
        "codex",
        "cursor",
        "gemini-cli",
        "opencode",
        "swift"
      ],
      "required_checks": [
        "policy / policy",
        "validate / swift-package",
        "smoke",
        "presentation / presentation"
      ],
      "release_tag_patterns": [
        "refs/tags/[0-9]*.[0-9]*.[0-9]*"
      ]
    },
    "example-org/homebrew-tap": {
      "default_branch": "master",
      "description": "Install agents with Homebrew.",
      "topics": [
        "homebrew",
        "homebrew-tap"
      ],
      "required_checks": [
        "policy / policy",
        "homebrew",
        "presentation / presentation"
      ],
      "release_tag_patterns": []
    },
    "example-org/agents-tools.github.io": {
      "default_branch": "master",
      "description": "Source for the agents website.",
      "topics": [],
      "required_checks": [
        "policy / policy",
        "site"
      ],
      "release_tag_patterns": []
    },
    "example-org/.github-private": {
      "default_branch": "master",
      "description": "Member dashboard for agents maintenance.",
      "topics": [],
      "visibility": "private",
      "required_checks": [
        "policy / policy",
        "check / profile"
      ],
      "release_tag_patterns": [],
      "enforcement_gap": "Repository rulesets are unavailable for private repositories on the Free plan."
    }
  }
}
```
