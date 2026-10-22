<script lang="ts">
	import MonitorIcon from '@lucide/svelte/icons/monitor';
	import MoonIcon from '@lucide/svelte/icons/moon';
	import SunIcon from '@lucide/svelte/icons/sun';
	import * as DropdownMenu from '$lib/components/ui/dropdown-menu';
	import { buttonVariants } from '$lib/components/ui/button';
	import { setPreference, theme, type ThemePreference } from '$lib/theme.svelte';

	const OPTIONS: { value: ThemePreference; label: string }[] = [
		{ value: 'light', label: 'Light' },
		{ value: 'dark', label: 'Dark' },
		{ value: 'system', label: 'System' }
	];
</script>

<DropdownMenu.Root>
	<DropdownMenu.Trigger class={buttonVariants({ variant: 'ghost', size: 'icon-sm' })} aria-label="Theme: {theme.preference}" title="Theme">
		{#if theme.resolved === 'dark'}<MoonIcon class="size-4" />{:else}<SunIcon class="size-4" />{/if}
	</DropdownMenu.Trigger>
	<DropdownMenu.Content align="end" class="w-36">
		<DropdownMenu.RadioGroup value={theme.preference} onValueChange={(v) => setPreference(v as ThemePreference)}>
			{#each OPTIONS as option (option.value)}
				<DropdownMenu.RadioItem value={option.value}>
					{#if option.value === 'light'}<SunIcon class="size-4" />{:else if option.value === 'dark'}<MoonIcon class="size-4" />{:else}<MonitorIcon class="size-4" />{/if}
					{option.label}
				</DropdownMenu.RadioItem>
			{/each}
		</DropdownMenu.RadioGroup>
	</DropdownMenu.Content>
</DropdownMenu.Root>
