<script lang="ts">
	// A native <select> in the Input look. Native so the browser menu, keyboard and form semantics stay intact.
	import { cn, type WithElementRef } from '$lib/utils.js';
	import type { HTMLSelectAttributes } from 'svelte/elements';

	let {
		ref = $bindable(null),
		value = $bindable(),
		class: className,
		children,
		...restProps
	}: WithElementRef<HTMLSelectAttributes, HTMLSelectElement> = $props();
</script>

<select bind:this={ref} bind:value data-slot="native-select" class={cn('field', className)} {...restProps}>
	{@render children?.()}
</select>
