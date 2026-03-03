---
description: "gitmoji"
---

Generate commit messages following Gitmoji conventions based on code changes.

## Format
```
:emoji_code: <message>

<detailed description>
```

## Common Emoji Code Selection Table

**Bug Fixes:**
- `:bug:` Fix bugs
- `:ambulance:` Critical hotfix
- `:lock:` Fix security issues

**New Features:**
- `:sparkles:` New features
- `:zap:` Performance improvements
- `:lipstick:` UI/style updates

**Documentation & Configuration:**
- `:memo:` Update documentation
- `:wrench:` Configuration files
- `:hammer:` Development scripts

**Others:**
- `:microscope:` Testing related
- `:construction:` Work in progress
- `:fire:` Remove content
- `:rocket:` Deploy/release

## Writing Requirements

1. **Message**: Start with a verb, within 50 characters (e.g., \"Fix user login bug\")
2. **Detailed description**: Explain the reason and impact of changes
3. **Choose appropriate emoji code**: Select based on the main type of change

## Example
```
:sparkles: Add Google OAuth login functionality

Implement OAuth2 flow to allow users to log in with their Google accounts. This reduces registration steps and provides a more secure authentication method.

Includes token validation, user information mapping, and session management features.
```

---

## Action Instructions

Based on the user's input, summarize the code updates and generate an English commit message following the Gitmoji format defined above. 

**Output Action:**  
Create or overwrite a file named `commit_message.md` in the root directory with the generated content.

**Trigger Handling:**

1.  **If user asks for "本次提交修改" (Staged Changes):**
    -   Analyze the changes in the git staging area (equivalent to `git diff --cached` or `git diff --staged`).
    -   **Constraint:** You must read the actual diff content line-by-line. Do not assume context outside of these changes.

2.  **If user asks for "本次分支修改" (Branch Changes):**
    -   Analyze the difference between the current branch and the `main` branch (equivalent to `git diff main...HEAD`).
    -   Summarize the cumulative work done on this branch.

**Final Reminder:**  
After creating the file, please remind the user to exclude `commit_message.md` from the commit to avoid committing the message file itself.

---
**Usage Instructions**: Please tell me about your code changes, and I will generate the corresponding commit message.