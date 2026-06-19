# SSO rollout

Single sign-on rollouts require identity provider metadata, an ACS URL, and a
certificate rotation plan. The rollout owner tests a pilot group before
enforcing SSO across the workspace.

Certificate rotation is safe when the old and new signing certificates overlap
for one week. Do not rotate during an unrelated checkout incident.
