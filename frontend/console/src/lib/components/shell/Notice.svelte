<script lang="ts">
	// One-line feedback under a form or list: error (role alert), success / status, warning hint.
	import type { Snippet } from 'svelte';
	import CircleAlertIcon from '@lucide/svelte/icons/circle-alert';
	import CircleCheckIcon from '@lucide/svelte/icons/circle-check';
	import InfoIcon from '@lucide/svelte/icons/info';
	import TriangleAlertIcon from '@lucide/svelte/icons/triangle-alert';
	import { cn } from '$lib/utils';

	type Tone = 'error' | 'success' | 'warning' | 'info';

	interface Props {
		tone: Tone;
		/** the element's text is the message itself, so tests and screen readers read it unchanged */
		children: Snippet;
		class?: string;
	}

	let { tone, children, class: className }: Props = $props();
	const STYLE: Record<Tone, string> = {
		error: 'text-hard',
		success: 'text-ok',
		warning: 'text-warn',
		info: 'text-muted-foreground'
	};
</script>

<p
	role={tone === 'error' ? 'alert' : tone === 'success' ? 'status' : undefined}
	class={cn('m-0 flex items-start gap-1.5 text-sm', STYLE[tone], className)}
>
	<span class="mt-0.5 shrink-0" aria-hidden="true">
		{#if tone === 'error'}<CircleAlertIcon class="size-3.5" />{:else if tone === 'success'}<CircleCheckIcon class="size-3.5" />{:else if tone === 'warning'}<TriangleAlertIcon
				class="size-3.5"
			/>{:else}<InfoIcon class="size-3.5" />{/if}
	</span>
	<span>{@render children()}</span>
</p>
