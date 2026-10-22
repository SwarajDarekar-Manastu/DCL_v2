<script lang="ts">
	import { session } from '$lib/auth/session.svelte';
	import EmptyState from '$lib/components/shell/EmptyState.svelte';
	import Page from '$lib/components/shell/Page.svelte';
	import RoleGate from '$lib/components/shell/RoleGate.svelte';
</script>

<RoleGate roles={session.user?.roles ?? []} role="viewer">
	<Page title="Ops" description="Sync status, queue depths, failed tasks and cost today (file 08 §4.2).">
		<EmptyState
			title="No operations data yet"
			description="Sync freshness per root, Celery queue depths, failed tasks with retry, and today's model cost against the budget will appear here once the ops API is connected."
		/>
	</Page>
</RoleGate>
