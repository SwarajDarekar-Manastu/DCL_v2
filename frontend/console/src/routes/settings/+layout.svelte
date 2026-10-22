<script lang="ts">
	import { page } from '$app/state';
	import { session } from '$lib/auth/session.svelte';
	import Page from '$lib/components/shell/Page.svelte';
	import RoleGate from '$lib/components/shell/RoleGate.svelte';
	import SectionMenu from '$lib/components/settings/SectionMenu.svelte';

	let { children } = $props();
</script>

<RoleGate roles={session.user?.roles ?? []} role="admin">
	<Page title="Settings" description="Pipeline configuration stored in pipeline_config. Secrets and endpoints stay in .env.">
		<div class="grid items-start gap-6 lg:grid-cols-[13rem_minmax(0,1fr)]">
			<div class="lg:sticky lg:top-[calc(var(--sticky-top,0px)+1.25rem)]">
				<SectionMenu current={page.params.section ?? (page.url.pathname === '/settings/users' ? 'users' : '')} />
			</div>
			<section class="panel min-w-0">{@render children()}</section>
		</div>
	</Page>
</RoleGate>
