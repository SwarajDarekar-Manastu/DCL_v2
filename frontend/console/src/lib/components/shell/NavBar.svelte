<script lang="ts">
	import { visibleNav } from '$lib/auth/roles';
	import type { ConsoleUser, LiveStatus } from '$lib/api_endpoint';

	interface Props {
		user: ConsoleUser;
		currentPath: string;
		reviewCounts?: { hard: number; soft: number } | null;
		liveStatus?: LiveStatus;
		onSignOut: () => void;
	}

	let { user, currentPath, reviewCounts = null, liveStatus = 'closed', onSignOut }: Props = $props();
	let items = $derived(visibleNav(user.roles));
</script>

<header class="navbar">
	<a class="brand" href="/">DCL Console</a>
	<nav aria-label="Console areas">
		{#each items as item (item.href)}
			<a href={item.href} aria-current={currentPath.startsWith(item.href) ? 'page' : undefined}>
				{item.label}
				{#if item.href === '/review' && reviewCounts}
					<span class="badge" title="open cases"
						><span class="hard">●{reviewCounts.hard} HARD</span> / {reviewCounts.soft} SOFT</span
					>
				{/if}
			</a>
		{/each}
	</nav>
	<div class="user">
		<span class="live live-{liveStatus}" title="live updates: {liveStatus}" aria-label="live updates {liveStatus}"></span>
		<span class="name">{user.name}</span>
		<span class="roles">{user.roles.at(-1)}</span>
		<button type="button" onclick={onSignOut}>Sign out</button>
	</div>
</header>

<style>
	.navbar {
		display: flex;
		align-items: center;
		gap: 1.5rem;
		padding: 0 1rem;
		height: 3rem;
		background: var(--surface-strong);
		color: var(--on-strong);
		flex-wrap: wrap;
	}
	.brand {
		font-weight: 700;
		color: inherit;
		text-decoration: none;
	}
	nav {
		display: flex;
		gap: 0.25rem;
		flex: 1;
		overflow-x: auto;
	}
	nav a {
		color: inherit;
		text-decoration: none;
		padding: 0.35rem 0.65rem;
		border-radius: 0.3rem;
		white-space: nowrap;
	}
	nav a[aria-current='page'],
	nav a:hover {
		background: var(--surface-strong-hover);
	}
	.badge {
		font-size: 0.8rem;
		margin-left: 0.35rem;
		opacity: 0.9;
	}
	.hard {
		color: var(--hard);
	}
	.user {
		display: flex;
		align-items: center;
		gap: 0.6rem;
		font-size: 0.875rem;
	}
	.roles {
		padding: 0.1rem 0.45rem;
		border: 1px solid currentColor;
		border-radius: 1rem;
		font-size: 0.75rem;
	}
	.live {
		width: 0.55rem;
		height: 0.55rem;
		border-radius: 50%;
		background: var(--muted);
	}
	.live-open {
		background: var(--ok);
	}
	.live-connecting {
		background: var(--warn);
	}
	button {
		background: transparent;
		color: inherit;
		border: 1px solid currentColor;
		border-radius: 0.3rem;
		padding: 0.2rem 0.6rem;
		cursor: pointer;
	}
</style>
