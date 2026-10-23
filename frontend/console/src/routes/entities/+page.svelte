<script lang="ts">
	import { session } from '$lib/auth/session.svelte';
	import EntitiesPanel from '$lib/components/entities/EntitiesPanel.svelte';
	import Page from '$lib/components/shell/Page.svelte';
	import RoleGate from '$lib/components/shell/RoleGate.svelte';
</script>

<RoleGate roles={session.user?.roles ?? []} role="reviewer">
	<Page title="Entities" description="Canonical entities with their aliases and mentions; merge duplicates, split wrong merges (file 08 §4.2).">
		<EntitiesPanel />
	</Page>
</RoleGate>
