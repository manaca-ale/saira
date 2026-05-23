# User-prompt builders (referência)

Funções que constroem o prompt do usuário (não o system prompt). Snapshot do `inspect.getsource()` para referência.


## `detector_gemini._new_litter_user_prompt`

```python
def _new_litter_user_prompt(
    first_frame_name: str,
    last_frame_name: str,
    camera_context: Optional[dict[str, str]] = None,
    prior_window_context: Optional[str] = None,
    mosaic: bool = False,
    mid_frame_names: Optional[list[str]] = None,
) -> str:
    context_lines = []
    if camera_context:
        for key, value in camera_context.items():
            if value:
                context_lines.append(f"- {key}: {value}")
    context_block = "\n".join(context_lines) if context_lines else "- sem contexto adicional"

    prior_block = ""
    if prior_window_context:
        prior_block = f"\nPrior window context:\n{prior_window_context}\n"

    mid_block = ""
    if mid_frame_names:
        labels = ", ".join(mid_frame_names)
        mid_block = f"Mid-window frames (25%/50%/75%): {labels}\n"

    json_fields = (
        "Return JSON: scene_type, vehicle_stopped, person_handling_material, "
        "new_ground_material, new_litter_detected, confidence_0_100, evidence_summary, "
        "first_frame_has_litter, last_frame_has_litter, waste_type, raw_reason_codes, "
        "scene_delta_analysis.\n"
    )

    if mosaic:
        frame_desc = (
            f"The single image provided is a side-by-side composite: "
            f"LEFT = initial frame ({first_frame_name}), RIGHT = final frame ({last_frame_name}). "
            "Compare the left half vs the right half."
        )
        return (
            f"{frame_desc}\n"
            f"{mid_block}"
            f"{json_fields}"
            f"{prior_block}"
            "Camera context:\n"
            f"{context_block}"
        )

    frame_lines = (
        f"Initial frame: {first_frame_name}\n"
        f"Final frame: {last_frame_name}\n"
        f"{mid_block}"
    )

    return (
        f"{frame_lines}"
        "Compare initial vs final frame. "
        "If a mid-window frame is provided, also check for Pattern C (ghost events).\n"
        f"{json_fields}"
        f"{prior_block}"
        "Camera context:\n"
        f"{context_block}"
    )
```

## `detector_gemini._user_prompt`

```python
def _user_prompt(
    camera_context: Optional[dict[str, str]] = None,
    frame_names: Optional[list[str]] = None,
    mosaic_mode: str = "off",
    prior_window_context: Optional[str] = None,
) -> str:
    context_lines = []
    if camera_context:
        for key, value in camera_context.items():
            if value:
                context_lines.append(f"- {key}: {value}")

    context_block = "\n".join(context_lines) if context_lines else "- sem contexto adicional"

    prior_block = ""
    if prior_window_context:
        prior_block = f"\nPrior window context:\n{prior_window_context}\n"

    if mosaic_mode != "off":
        if mosaic_mode == "4x3":
            frame_desc = (
                "The image(s) provided are a 4-row × 3-column mosaic grid of frames "
                "numbered 1-12 (left-to-right, top-to-bottom, chronological order). "
                "Frame 1 is earliest, frame 12 is latest. "
                "Use 'frame_N' (e.g. 'frame_7') as event_frame_name and offender_frame_name."
            )
        else:  # 3x2split
            frame_desc = (
                "Two mosaic images are provided: the first contains frames 1-6 "
                "(3 columns × 2 rows, chronological), the second contains frames 7-12. "
                "Frame 1 is earliest, frame 12 is latest. "
                "Use 'frame_N' (e.g. 'frame_7') as event_frame_name and offender_frame_name."
            )
        return (
            "Analise a sequencia temporal de imagens e retorne JSON estruturado com:\n"
            "1) confirmacao de infracao\n"
            "2) confianca 0..100\n"
            "3) resumo factual curto da evidencia\n"
            "4) classificacao de residuo/material e volume aproximado\n"
            "5) dados de infrator e dados veiculares quando visiveis (opcional)\n"
            "6) event_frame_name e offender_frame_name usando o formato 'frame_N'\n"
            f"Regra de decisao: infraction_confirmed=true pode ocorrer mesmo com offender_detected=false.\n"
            f"Formato das imagens: {frame_desc}\n"
            f"{prior_block}"
            "Contexto da camera:\n"
            f"{context_block}"
        )

    frame_block = ", ".join(frame_names) if frame_names else "desconhecido"
    return (
        "Analise a sequencia temporal de imagens e retorne JSON estruturado com:\n"
        "1) confirmacao de infracao\n"
        "2) confianca 0..100\n"
        "3) resumo factual curto da evidencia\n"
        "4) classificacao de residuo/material e volume aproximado\n"
        "5) dados de infrator e dados veiculares quando visiveis (opcional)\n"
        "6) event_frame_name e offender_frame_name escolhidos somente dentre os nomes permitidos\n"
        "Regra de decisao: infraction_confirmed=true pode ocorrer mesmo com offender_detected=false.\n"
        f"Nomes de frame permitidos: {frame_block}\n"
        f"{prior_block}"
        "Contexto da camera:\n"
        f"{context_block}"
    )
```

## `_prompts_v2.build_v2_user_prompt_gate`

```python
def build_v2_user_prompt_gate(
    first_frame_name: str,
    last_frame_name: str,
    camera_context: Optional[dict[str, str]] = None,
    prior_window_context: Optional[str] = None,
    mosaic: bool = False,
    mid_frame_names: Optional[list[str]] = None,
) -> str:
    """V2 user prompt for Agent-1 (gate). Adds LOCAL_CONTEXT and pile-delta question."""
    context_lines = []
    local_notes = ""
    if camera_context:
        for key, value in camera_context.items():
            if not value:
                continue
            if key == "gemini_context_notes":
                local_notes = str(value).strip()
                continue
            context_lines.append(f"- {key}: {value}")
    context_block = "\n".join(context_lines) if context_lines else "- sem contexto adicional"

    prior_block = ""
    if prior_window_context:
        prior_block = f"\nPrior window context:\n{prior_window_context}\n"

    local_block = ""
    if local_notes:
        local_block = f"\nLOCAL_CONTEXT (this specific camera's known patterns):\n{local_notes}\n"

    mid_block = ""
    if mid_frame_names:
        labels = ", ".join(mid_frame_names)
        mid_block = f"Mid-window frames (25%/50%/75%): {labels}\n"

    json_fields = (
        "Return JSON with: scene_type, vehicle_stopped, person_handling_material, "
        "new_ground_material, material_flow_direction, pile_volume_change, "
        "municipal_equipment_present, new_litter_detected, confidence_0_100, "
        "evidence_summary, first_frame_has_litter, last_frame_has_litter, "
        "waste_type, raw_reason_codes, scene_delta_analysis.\n"
    )

    explicit_question = (
        "Compare the FIRST and LAST frame:\n"
        "1. Did the visible waste pile on the ground INCREASE, DECREASE, or stay roughly the same?\n"
        "2. Is the dominant material movement going TO the ground (dumping) or FROM the ground (collection)?\n"
        "3. Is a caminhao compactador (rear-hopper municipal truck) OR a wooden carroca clearly visible?\n"
    )

    if mosaic:
        frame_desc = (
            f"The image provided is a side-by-side composite: "
            f"LEFT = initial frame ({first_frame_name}), RIGHT = final frame ({last_frame_name}). "
            "Compare the left half vs the right half."
        )
        return (
            f"{frame_desc}\n"
            f"{mid_block}"
            f"{explicit_question}"
            f"{json_fields}"
            f"{prior_block}"
            f"{local_block}"
            "Camera context:\n"
            f"{context_block}"
        )

    frame_lines = (
        f"Initial frame: {first_frame_name}\n"
        f"Final frame: {last_frame_name}\n"
        f"{mid_block}"
    )
    return (
        f"{frame_lines}"
        f"{explicit_question}"
        "If a mid-window frame is provided, also check for Pattern C (ghost events).\n"
        f"{json_fields}"
        f"{prior_block}"
        f"{local_block}"
        "Camera context:\n"
        f"{context_block}"
    )
```

## `_prompts_v2.build_v2_user_prompt_detail`

```python
def build_v2_user_prompt_detail(
    camera_context: Optional[dict[str, str]] = None,
    frame_names: Optional[list[str]] = None,
    mosaic_mode: str = "off",
    prior_window_context: Optional[str] = None,
) -> str:
    """V2 user prompt for Agent-2 (detail). Adds LOCAL_CONTEXT block."""
    context_lines = []
    local_notes = ""
    if camera_context:
        for key, value in camera_context.items():
            if not value:
                continue
            if key == "gemini_context_notes":
                local_notes = str(value).strip()
                continue
            context_lines.append(f"- {key}: {value}")
    context_block = "\n".join(context_lines) if context_lines else "- sem contexto adicional"

    prior_block = ""
    if prior_window_context:
        prior_block = f"\nPrior window context:\n{prior_window_context}\n"

    local_block = ""
    if local_notes:
        local_block = f"\nLOCAL_CONTEXT (this specific camera's known patterns):\n{local_notes}\n"

    if mosaic_mode != "off":
        if mosaic_mode == "4x3":
            frame_desc = (
                "The image(s) provided are a 4-row x 3-column mosaic grid of frames "
                "numbered 1-12 (left-to-right, top-to-bottom, chronological order). "
                "Frame 1 is earliest, frame 12 is latest. "
                "Use 'frame_N' (e.g. 'frame_7') as event_frame_name and offender_frame_name."
            )
        else:  # 3x2split
            frame_desc = (
                "Two mosaic images are provided: the first contains frames 1-6 "
                "(3 columns x 2 rows, chronological), the second contains frames 7-12. "
                "Frame 1 is earliest, frame 12 is latest. "
                "Use 'frame_N' (e.g. 'frame_7') as event_frame_name and offender_frame_name."
            )
        return (
            "Analise a sequencia temporal de imagens e retorne JSON estruturado com:\n"
            "1) confirmacao de infracao (infraction_confirmed)\n"
            "2) confianca 0..100\n"
            "3) resumo factual curto da evidencia\n"
            "4) classificacao de residuo/material e volume aproximado\n"
            "5) dados de infrator e dados veiculares quando visiveis (opcional)\n"
            "6) event_frame_name e offender_frame_name usando o formato 'frame_N'\n"
            "Regra de decisao: infraction_confirmed=true pode ocorrer mesmo com offender_detected=false.\n"
            "Discriminador chave: material indo PARA o chao = DESCARTE; material indo DO chao = COLETA.\n"
            f"Formato das imagens: {frame_desc}\n"
            f"{prior_block}"
            f"{local_block}"
            "Contexto da camera:\n"
            f"{context_block}"
        )

    frame_block = ", ".join(frame_names) if frame_names else "desconhecido"
    return (
        "Analise a sequencia temporal de imagens e retorne JSON estruturado com:\n"
        "1) confirmacao de infracao (infraction_confirmed)\n"
        "2) confianca 0..100\n"
        "3) resumo factual curto da evidencia\n"
        "4) classificacao de residuo/material e volume aproximado\n"
        "5) dados de infrator e dados veiculares quando visiveis (opcional)\n"
        "6) event_frame_name e offender_frame_name escolhidos somente dentre os nomes permitidos\n"
        "Regra de decisao: infraction_confirmed=true pode ocorrer mesmo com offender_detected=false.\n"
        "Discriminador chave: material indo PARA o chao = DESCARTE; material indo DO chao = COLETA.\n"
        f"Nomes de frame permitidos: {frame_block}\n"
        f"{prior_block}"
        f"{local_block}"
        "Contexto da camera:\n"
        f"{context_block}"
    )
```
