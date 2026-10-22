<script lang="ts">
	import { session } from '$lib/auth/session.svelte';
	import EmptyState from '$lib/components/shell/EmptyState.svelte';
	import Page from '$lib/components/shell/Page.svelte';
	import RoleGate from '$lib/components/shell/RoleGate.svelte';
</script>

<RoleGate roles={session.user?.roles ?? []} role="viewer">
	<Page title="Entities" description="Canonical entities and alias merges (file 08 §4.2).">
		<EmptyState
			title="No entity data yet"
			description="Canonical entities (propellants, components, test articles, vendors) with their aliases, mention counts and merge proposals will be listed here once the entity API is connected."
		/>
	</Page>
</RoleGate>
