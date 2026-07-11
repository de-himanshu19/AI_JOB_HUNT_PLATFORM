# Cover Letters

Milestone 24 adds a dashboard-native, local cover-letter workspace. Select a
job, open **Job Detail**, and use the **Cover Letter** tab to generate, review,
edit, and copy a conservative draft. Nothing is sent, uploaded, or submitted.

## Rule-Based Drafts

Rule-based drafts use the stored candidate profile, job title, company,
location, description completeness, and evidence-backed skills and experience.
They use `Dear Hiring Team` rather than inventing a recruiter name. Drafts and
metadata are stored under ignored `data/cover_letters/`.

Snippet-only jobs display a warning. Paste the full vacancy description in the
dashboard for better tailoring; pasted text is used for that generation only
and does not replace the stored authoritative description.

## Templates

Safe local Markdown templates live in `config/cover_letter_templates/` and use
`${placeholder}` values. The committed `example_english.md` demonstrates:
`candidate_name`, `company`, `job_title`, `location`, `relevant_experience`,
`relevant_skills`, `availability`, `work_authorization`, and `closing`.

## Optional AI Polish

AI polish requires an explicit confirmation and click. The rule-based draft is
the parent and remains unchanged. The derivative is saved only when validation
preserves protected facts and rejects invented recruiters, changed dates, and
unsupported stronger wording. Validation failure leaves the original draft in
the workspace.

Always review the final text before copying it into an application. The
platform does not auto-apply, send email, or contact recruiters.
