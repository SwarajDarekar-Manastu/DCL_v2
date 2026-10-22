<script lang="ts">
	import '../app.css';
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import LayersIcon from '@lucide/svelte/icons/layers';
	import LoaderCircleIcon from '@lucide/svelte/icons/loader-circle';
	import { openLiveChannel, type LiveChannel } from '$lib/api_endpoint';
	import { applyLiveEvent, live } from '$lib/live.svelte';
	import { hasRole } from '$lib/auth/roles';
	import { session, startSession } from '$lib/auth/session.svelte';
	import { Button } from '$lib/components/ui/button';
	import * as Tooltip from '$lib/components/ui/tooltip';
	import { documentTitle } from '$lib/components/shell/breadcrumbs';
	import Notice from '$lib/components/shell/Notice.svelte';
	import Sidebar from '$lib/components/shell/Sidebar.svelte';
	import TopBar from '$lib/components/shell/TopBar.svelte';
	import { startTheme } from '$lib/theme.svelte';

	let { children } = $props();

	onMount(() => {
		startSession();
		return startTheme();
	});

	$effect(() => {
		const user = session.user;
		if (session.status !== 'signed_in' || !user) return;
		const channel: LiveChannel = openLiveChannel({
			topics: hasRole(user.roles, 'reviewer') ? ['ops', 'run', 'case'] : ['ops', 'run'],
			onStatus: (status) => (live.status = status),
			onEvent: applyLiveEvent
		});
		return () => channel.close();
	});
</script>

<svelte:head><title>{documentTitle(page.url.pathname)}</title></svelte:head>

{#if session.status === 'loading'}
	<main class="flex min-h-screen items-center justify-center">
		<p class="text-muted-foreground flex items-center gap-2" role="status">
			<LoaderCircleIcon class="size-4 animate-spin" aria-hidden="true" /> Signing in…
		</p>
	</main>
{:else if session.status === 'signed_out' || session.status === 'error'}
	<main class="flex min-h-screen items-center justify-center p-6">
		<div class="bg-card w-full max-w-sm rounded-xl border p-8 text-center shadow-sm">
			<span class="bg-primary text-primary-foreground mx-auto mb-5 flex size-10 items-center justify-center rounded-lg" aria-hidden="true">
				<LayersIcon class="size-5" />
			</span>
			{#if session.status === 'error'}
				<h1 class="m-0 text-lg">Sign-in failed</h1>
				<Notice tone="error" class="mt-3 justify-center text-left">{session.error}</Notice>
				<Button class="mt-6 w-full" onclick={() => startSession()}>Try again</Button>
			{:else}
				<h1 class="m-0 text-lg">DCL Console</h1>
				<p class="text-muted-foreground mt-1">Review, benchmarks and configuration for the Document Context Layer.</p>
				<Button class="mt-6 w-full" onclick={() => session.signIn()}>Sign in with Microsoft</Button>
			{/if}
		</div>
	</main>
{:else if session.user}
	<Tooltip.Provider delayDuration={300}>
		<a
			href="#main"
			class="bg-primary text-primary-foreground sr-only z-50 rounded-md px-3 py-2 no-underline focus:not-sr-only focus:fixed focus:top-2 focus:left-2"
			>Skip to content</a
		>
		<div class="flex min-h-screen">
			<Sidebar
				user={session.user}
				currentPath={page.url.pathname}
				reviewCounts={live.reviewCounts}
				liveStatus={live.status}
				onSignOut={() => session.signOut()}
			/>
			<div class="flex min-w-0 flex-1 flex-col">
				<TopBar pathname={page.url.pathname} />
				<main id="main" tabindex="-1" class="flex min-w-0 flex-1 flex-col outline-none [--sticky-top:3rem]">
					{@render children()}
				</main>
			</div>
		</div>
	</Tooltip.Provider>
{/if}
