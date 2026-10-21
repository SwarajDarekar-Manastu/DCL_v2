<script lang="ts">
	import '../app.css';
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import { openLiveChannel, type LiveChannel } from '$lib/api_endpoint';
	import { applyLiveEvent, live } from '$lib/live.svelte';
	import { hasRole } from '$lib/auth/roles';
	import { session, startSession } from '$lib/auth/session.svelte';
	import { getConfig } from '$lib/config';
	import NavBar from '$lib/components/shell/NavBar.svelte';

	let { children } = $props();

	onMount(() => {
		startSession();
	});

	$effect(() => {
		const user = session.user;
		if (session.status !== 'signed_in' || !user || getConfig().auth.mode === 'dev') return;
		const channel: LiveChannel = openLiveChannel({
			topics: hasRole(user.roles, 'reviewer') ? ['ops', 'run', 'case'] : ['ops', 'run'],
			onStatus: (status) => (live.status = status),
			onEvent: applyLiveEvent
		});
		return () => channel.close();
	});
</script>

{#if session.status === 'loading'}
	<main class="center"><p>Signing in…</p></main>
{:else if session.status === 'signed_out'}
	<main class="center">
		<h1>DCL Console</h1>
		<p>Review, benchmarks and configuration for the Document Context Layer.</p>
		<button type="button" class="primary" onclick={() => session.signIn()}>Sign in with Microsoft</button>
	</main>
{:else if session.status === 'error'}
	<main class="center" role="alert">
		<h1>Sign-in failed</h1>
		<p>{session.error}</p>
		<button type="button" class="primary" onclick={() => startSession()}>Try again</button>
	</main>
{:else if session.user}
	<NavBar
		user={session.user}
		currentPath={page.url.pathname}
		reviewCounts={live.reviewCounts}
		liveStatus={live.status}
		onSignOut={() => session.signOut()}
	/>
	<main class="content">
		{@render children()}
	</main>
{/if}

<style>
	.center {
		max-width: 28rem;
		margin: 18vh auto 0;
		padding: 0 1rem;
		text-align: center;
	}
	.content {
		padding: 1rem;
	}
	.primary {
		background: var(--accent);
		color: white;
		border: 0;
		border-radius: 0.35rem;
		padding: 0.6rem 1.2rem;
		font-size: 1rem;
		cursor: pointer;
	}
</style>
