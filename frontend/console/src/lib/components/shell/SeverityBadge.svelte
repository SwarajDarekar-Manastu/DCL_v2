<script lang="ts">
	import ToneBadge from './ToneBadge.svelte';

	interface Props {
		severity: 'HARD' | 'SOFT' | string;
		class?: string;
	}

	let { severity, class: className }: Props = $props();
</script>

<ToneBadge tone={severity === 'HARD' ? 'hard' : 'warn'} class={className}>{severity}</ToneBadge>
