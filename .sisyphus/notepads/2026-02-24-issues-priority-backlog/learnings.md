# Learnings
Closed issue #6: build_messages signature already clean (2 args) on main.
_is_owner can stay single-pass by tracking an unscoped match flag while continuing to scan for a scoped match.
The safe flow is: return immediately on scoped equality, defer unscoped True until after the loop.
A spy alias with side-effecting channel property makes precedence observable and catches early unscoped returns.
PR #13: https://github.com/Athemis/squidbot/pull/13
PR #12: https://github.com/Athemis/squidbot/pull/12
Issue #5 closed via PR #13 merge; issue #4 closed via PR #12 merge.
