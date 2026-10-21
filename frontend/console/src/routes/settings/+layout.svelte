<script lang="ts">
	import { page } from '$app/state';
	import { session } from '$lib/auth/session.svelte';
	import RoleGate from '$lib/components/shell/RoleGate.svelte';
	import SectionMenu from '$lib/components/settings/SectionMenu.svelte';

	let { children } = $props();
</script>

<RoleGate roles={session.user?.roles ?? []} role="admin">
	<div class="settings">
		<SectionMenu current={page.params.section ?? ''} />
		<section>{@render children()}</section>
	</div>
</RoleGate>

<style>
	.settings {
		display: grid;
		grid-template-columns: 13rem minmax(0, 1fr);
		gap: 1.5rem;
		align-items: start;
	}
	@media (max-width: 700px) {
		.settings {
			grid-template-columns: 1fr;
		}
	}
</style>
