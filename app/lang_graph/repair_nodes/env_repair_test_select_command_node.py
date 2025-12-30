"""Node: Select testsuite commands to execute based on level strategy (no model needed).

Goal:
- Prefer executing the TARGET level first (smallest level that exists, usually Level 1).
- If TARGET fails, progressively add auxiliary levels (2-4) for diagnosis/support.
- After environment changes (env command history advances), reset back to TARGET-only.

This node outputs `test_command` as an ordered list of shell commands (strings).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from langchain_core.language_models.chat_models import BaseChatModel

from app.container.base_container import BaseContainer
from app.utils.logger_manager import get_thread_logger


class EnvRepairTestSelectCommandNode:
    """Select which testsuite commands to run next based on level1-4 availability and last outcome."""

    def __init__(self, model: Optional[BaseChatModel] = None, container: Optional[BaseContainer] = None):
        # model is intentionally unused; kept for API compatibility with existing wiring
        self.model = model
        self.container = container
        self._logger, _file_handler = get_thread_logger(__name__)

    @staticmethod
    def _normalize_commands(value: Any) -> List[str]:
        """Convert various command representations into a list[str]."""
        if value is None:
            return []
        if isinstance(value, str):
            cmd = value.strip()
            return [cmd] if cmd else []
        if isinstance(value, (list, tuple)):
            out: List[str] = []
            for item in value:
                out.extend(EnvRepairTestSelectCommandNode._normalize_commands(item))
            return [c for c in out if c]
        if isinstance(value, dict):
            # common shapes: {"command": "..."} or {"content": "..."}
            if "command" in value:
                return EnvRepairTestSelectCommandNode._normalize_commands(value.get("command"))
            if "content" in value:
                return EnvRepairTestSelectCommandNode._normalize_commands(value.get("content"))
        # fallback: stringify
        cmd = str(value).strip()
        return [cmd] if cmd else []

    @staticmethod
    def _dedupe_preserve_order(cmds: List[str]) -> List[str]:
        seen = set()
        out: List[str] = []
        for c in cmds:
            c = c.strip()
            if not c or c in seen:
                continue
            seen.add(c)
            out.append(c)
        return out

    @staticmethod
    def _extract_level_commands(state: Dict) -> Dict[int, List[str]]:
        """
        Extract level commands from state.testsuite_commands.
        Expected generation-mode shape:
          {"level1_commands": [...], "level2_commands": [...], ...}
        """
        testsuite_commands = state.get("testsuite_commands", {})
        level_map: Dict[int, List[str]] = {1: [], 2: [], 3: [], 4: []}

        if isinstance(testsuite_commands, dict):
            level_map[1] = EnvRepairTestSelectCommandNode._dedupe_preserve_order(
                EnvRepairTestSelectCommandNode._normalize_commands(testsuite_commands.get("level1_commands", []))
            )
            level_map[2] = EnvRepairTestSelectCommandNode._dedupe_preserve_order(
                EnvRepairTestSelectCommandNode._normalize_commands(testsuite_commands.get("level2_commands", []))
            )
            level_map[3] = EnvRepairTestSelectCommandNode._dedupe_preserve_order(
                EnvRepairTestSelectCommandNode._normalize_commands(testsuite_commands.get("level3_commands", []))
            )
            level_map[4] = EnvRepairTestSelectCommandNode._dedupe_preserve_order(
                EnvRepairTestSelectCommandNode._normalize_commands(testsuite_commands.get("level4_commands", []))
            )
            return level_map

        # CI/CD or pytest modes might store commands as list[str]; treat as "level1" to stay compatible.
        flat = EnvRepairTestSelectCommandNode._dedupe_preserve_order(
            EnvRepairTestSelectCommandNode._normalize_commands(testsuite_commands)
        )
        level_map[1] = flat
        return level_map

    @staticmethod
    def _pick_target_and_ordered_levels(level_map: Dict[int, List[str]]) -> Tuple[Optional[int], List[int]]:
        available = [lvl for lvl in [1, 2, 3, 4] if level_map.get(lvl)]
        if not available:
            return None, []
        target = min(available)
        ordered = [target] + [lvl for lvl in available if lvl != target]
        return target, ordered

    @staticmethod
    def _env_version(state: Dict) -> int:
        """A cheap heuristic: env history length increments whenever env script is (re)executed."""
        hist = state.get("env_command_result_history", [])
        return len(hist) if isinstance(hist, list) else 0

    def __call__(self, state: Dict):
        level_map = self._extract_level_commands(state)
        target_level, ordered_levels = self._pick_target_and_ordered_levels(level_map)

        # Fallback: if we can't detect levels, keep current test_command as-is.
        if not target_level or not ordered_levels:
            existing = self._dedupe_preserve_order(self._normalize_commands(state.get("test_command", [])))
            self._logger.info(
                "No level commands found; keeping existing test_command."
            )
            return {"test_command": existing}

        # Strategy:
        # - Always run TARGET level first.
        # - Only if TARGET fails, run auxiliary levels (target+1..4 that exist) in order.
        target_commands = level_map.get(target_level, [])
        aux_levels = [lvl for lvl in ordered_levels if lvl != target_level]
        aux_by_level = {lvl: level_map.get(lvl, []) for lvl in aux_levels}

        self._logger.info(
            f"Selected TARGET level={target_level} (commands={len(target_commands)}); "
            f"aux_levels={aux_levels} (total_aux_cmds={sum(len(v) for v in aux_by_level.values())})"
        )

        return {
            # Backward-compatible: execute node reads `test_command`
            "test_command": target_commands,
            # New structured plan for conditional execution in execute node
            "test_target_level": target_level,
            "test_target_commands": target_commands,
            "test_aux_levels": aux_levels,
            "test_aux_commands_by_level": aux_by_level,
        }

