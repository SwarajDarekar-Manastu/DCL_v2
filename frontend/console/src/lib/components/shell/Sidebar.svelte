<script lang="ts">
	import type { Component } from 'svelte';
	import ActivityIcon from '@lucide/svelte/icons/activity';
	import ClipboardCheckIcon from '@lucide/svelte/icons/clipboard-check';
	import FlaskConicalIcon from '@lucide/svelte/icons/flask-conical';
	import LayersIcon from '@lucide/svelte/icons/layers';
	import LogOutIcon from '@lucide/svelte/icons/log-out';
	import ScrollTextIcon from '@lucide/svelte/icons/scroll-text';
	import Settings2Icon from '@lucide/svelte/icons/settings-2';
	import TagsIcon from '@lucide/svelte/icons/tags';
	import type { ConsoleUser, LiveStatus } from '$lib/api_endpoint';
	import { hasRole, visibleNav } from '$lib/auth/roles';
	import { cn } from '$lib/utils';

	interface Props {
		user: ConsoleUser;
		currentPath: string;
		reviewCounts?: { hard: number; soft: number } | null;
		liveStatus?: LiveStatus;
		onSignOut: () => void;
	}

	let { user, currentPath, reviewCounts = null, liveStatus = 'closed', onSignOut }: Props = $props();
	let items = $derived(visibleNav(user.roles));
	let role = $derived((['admin', 'reviewer', 'viewer'] as const).find((r) => hasRole(user.roles, r)) ?? 'viewer');
	const ROLE_LABEL = { admin: 'Admin', reviewer: 'Reviewer', viewer: 'Viewer' } as const;
	let initials = $derived(
		user.name
			.split(/\s+/)
			.filter(Boolean)
			.slice(0, 2)
			.map((w) => w[0]?.toUpperCase() ?? '')
			.join('') || '?'
	);

	const ICONS: Record<string, Component<{ class?: string }>> = {
		'/review': ClipboardCheckIcon,
		'/benchmark': FlaskConicalIcon,
		'/entities': TagsIcon,
		'/settings': Settings2Icon,
		'/ops': ActivityIcon,
		'/audit': ScrollTextIcon
	};
	const LIVE: Record<LiveStatus, { label: string; dot: string }> = {
		open: { label: 'Live updates', dot: 'bg-ok' },
		connecting: { label: 'Connecting', dot: 'bg-warn' },
		closed: { label: 'Offline', dot: 'bg-muted-foreground/50' }
	};
	const isCurrent = (href: string) => currentPath === href || currentPath.startsWith(`${href}/`);
</script>

<aside class="bg-sidebar text-sidebar-foreground sticky top-0 flex h-screen w-60 shrink-0 flex-col border-r">
	<a href="/" class="flex h-12 items-center gap-2.5 border-b px-4 text-foreground no-underline hover:no-underline">
		<span class="bg-primary text-primary-foreground flex size-6 items-center justify-center rounded-md" aria-hidden="true">
			<LayersIcon class="size-3.5" />
		</span>
		<span class="text-sm font-semibold tracking-tight">DCL Console</span>
	</a>

	<nav aria-label="Console areas" class="flex-1 overflow-y-auto px-2 py-3">
		<ul class="m-0 list-none space-y-0.5 p-0">
			{#each items as item (item.href)}
				{@const Icon = ICONS[item.href]}
				<li>
					<a
						href={item.href}
						aria-current={isCurrent(item.href) ? 'page' : undefined}
						class={cn(
							'text-muted-foreground hover:bg-sidebar-accent hover:text-foreground flex h-8 items-center gap-2.5 rounded-md px-2.5 text-sm font-medium no-underline transition-colors hover:no-underline',
							isCurrent(item.href) && 'bg-sidebar-accent text-foreground'
						)}
					>
						{#if Icon}<Icon class="size-4 shrink-0" />{/if}
						<span class="flex-1 truncate">{item.label}</span>
						{#if item.href === '/review' && reviewCounts}
							<span class="num flex items-center gap-1 text-[11px] font-medium" title="open cases">
								<span class={cn('rounded-sm px-1 leading-4', reviewCounts.hard ? 'bg-hard-bg text-hard' : 'bg-muted text-muted-foreground')}
									>{reviewCounts.hard} HARD</span
								>
								<span class="text-muted-foreground">/</span>
								<span class="text-muted-foreground">{reviewCounts.soft} SOFT</span>
							</span>
						{/if}
					</a>
				</li>
			{/each}
		</ul>
	</nav>

	<div class="space-y-3 border-t px-4 py-3">
		<p class="text-muted-foreground m-0 flex items-center gap-2 text-xs" aria-label="live updates {liveStatus}" title="live updates: {liveStatus}">
			<span class={cn('size-1.5 rounded-full', LIVE[liveStatus].dot)} aria-hidden="true"></span>
			{LIVE[liveStatus].label}
		</p>
		<div class="flex items-center gap-2.5">
			<span class="bg-muted text-foreground flex size-7 shrink-0 items-center justify-center rounded-full text-[11px] font-semibold" aria-hidden="true">
				{initials}
			</span>
			<div class="min-w-0 flex-1 leading-tight">
				<p class="m-0 truncate text-sm font-medium" title={user.email}>{user.name}</p>
				<p class="text-muted-foreground m-0 text-xs">{ROLE_LABEL[role]}</p>
			</div>
			<button
				type="button"
				class="text-muted-foreground hover:bg-sidebar-accent hover:text-foreground flex size-7 shrink-0 items-center justify-center rounded-md transition-colors"
				aria-label="Sign out"
				title="Sign out"
				onclick={onSignOut}
			>
				<LogOutIcon class="size-4" />
			</button>
		</div>
	</div>
</aside>
