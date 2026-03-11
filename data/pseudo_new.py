def aes_round(state):
    state = sub_bytes(state)
    state = shift_rows(state)
    if round_index < 5:
        state = mix_columns(state)
    state = add_round_key(state)
    state = insert_mask(state)
    return state
