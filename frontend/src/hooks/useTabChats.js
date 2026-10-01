import { useEffect, useState } from "react";

export function newId() {
    return `c${Date.now()}${Math.random().toString(36).slice(2, 6)}`;
}

function load(storeKey, legacy, blank) {
    try {
        const saved = JSON.parse(localStorage.getItem(storeKey));
        if (saved && Array.isArray(saved.chats) && saved.chats.length) return saved;
    } catch {}
    const first = { ...blank(), ...(legacy ? legacy() : {}), id: "c0" };
    return { chats: [first], activeId: first.id };
}

// Several saved chats per tab, kept on this device. `blank()` gives a new
// chat's fields (items, repo…); `legacy()` turns the old single-chat save
// into the first chat; `persist(chat)` trims what gets stored.
export default function useTabChats(storeKey, { blank, legacy, persist = c => c }) {
    const [state, setState] = useState(() => load(storeKey, legacy, blank));
    const chat = state.chats.find(c => c.id === state.activeId) || state.chats[0];

    useEffect(() => {
        try {
            localStorage.setItem(storeKey, JSON.stringify({ ...state, chats: state.chats.map(persist) }));
        } catch {}
    }, [state]); // eslint-disable-line react-hooks/exhaustive-deps

    const updateChat = (id, fn) => setState(s => ({
        ...s, chats: s.chats.map(c => (c.id === id ? { ...c, ...fn(c), updated: Date.now() } : c)),
    }));
    const newChat = (fields = {}) => {
        const c = { ...blank(), ...fields, id: newId(), title: "", updated: Date.now() };
        setState(s => ({ chats: [c, ...s.chats].slice(0, 50), activeId: c.id }));
        return c;
    };
    const selectChat = id => setState(s => ({ ...s, activeId: id }));
    const deleteChat = id => setState(s => {
        const rest = s.chats.filter(c => c.id !== id);
        const chats = rest.length ? rest : [{ ...blank(), id: newId(), title: "", updated: Date.now() }];
        return { chats, activeId: s.activeId === id ? chats[0].id : s.activeId };
    });

    return { chats: state.chats, chat, updateChat, newChat, selectChat, deleteChat };
}
