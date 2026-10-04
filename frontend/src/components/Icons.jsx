// Thin line icons (24px grid, 2px stroke, currentColor) — the one icon style used across the app.
function Svg({ size = 16, children, strokeWidth = 2 }) {
    return (
        <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={strokeWidth}
            strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" style={{ display: "block", flexShrink: 0 }}>
            {children}
        </svg>
    );
}

export const MenuIcon = (p) => <Svg {...p}><path d="M4 7h16M4 12h16M4 17h16" /></Svg>;
export const CloseIcon = (p) => <Svg {...p}><path d="M6 6l12 12M18 6 6 18" /></Svg>;
export const BackIcon = (p) => <Svg {...p}><path d="M15 18l-6-6 6-6" /></Svg>;
export const MoreIcon = (p) => <Svg {...p}><circle cx="5" cy="12" r="1" /><circle cx="12" cy="12" r="1" /><circle cx="19" cy="12" r="1" /></Svg>;
export const ActivityIcon = (p) => <Svg {...p}><path d="M3 12h4l3-8 4 16 3-8h4" /></Svg>;
export const ReceiptIcon = (p) => <Svg {...p}><path d="M6 3h12v18l-3-2-3 2-3-2-3 2V3z" /><path d="M9 8h6M9 12h6M9 16h3" /></Svg>;
export const SendIcon = (p) => <Svg {...p}><path d="M12 19V5M5 12l7-7 7 7" /></Svg>;
export const StopIcon = (p) => <Svg {...p}><rect x="6" y="6" width="12" height="12" rx="2" /></Svg>;
export const PlusIcon = (p) => <Svg {...p}><path d="M12 5v14M5 12h14" /></Svg>;
export const PaperclipIcon = (p) => <Svg {...p}><path d="M21 11.5 12.5 20a5 5 0 0 1-7-7L14 4.5a3.5 3.5 0 0 1 5 5L10.5 18a2 2 0 0 1-3-3L15 7.5" /></Svg>;
export const SlashIcon = (p) => <Svg {...p}><rect x="3" y="3" width="18" height="18" rx="3" /><path d="M14.5 7.5l-5 9" /></Svg>;
export const PlugIcon = (p) => <Svg {...p}><path d="M9 2v5M15 2v5M6 7h12v4a6 6 0 0 1-12 0V7zM12 17v5" /></Svg>;
export const FileIcon = (p) => <Svg {...p}><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><path d="M14 2v6h6" /></Svg>;
export const ChatIcon = (p) => <Svg {...p}><path d="M21 12a8 8 0 0 1-11.6 7.1L4 21l1.9-5.4A8 8 0 1 1 21 12z" /></Svg>;
export const CodeIcon = (p) => <Svg {...p}><path d="M8 7l-5 5 5 5M16 7l5 5-5 5" /></Svg>;
export const SparkleIcon = (p) => <Svg {...p}><path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8L12 3zM19 16l.7 2.3L22 19l-2.3.7L19 22l-.7-2.3L16 19l2.3-.7L19 16z" /></Svg>;
export const BrushIcon = (p) => <Svg {...p}><path d="M18.4 2.6a2 2 0 0 1 2.9 2.9L11 15.8 8.2 13 18.4 2.6zM7 14.5c-2 0-3.5 1.6-3.5 3.5 0 1.4-.8 2.3-1.5 2.5 1 .9 2.4 1.5 4 1.5 2.5 0 4.5-2 4.5-4.5L7 14.5z" /></Svg>;
export const WalletIcon = (p) => <Svg {...p}><path d="M20 7V5a2 2 0 0 0-2-2H5a2 2 0 0 0 0 4h15v14H5a2 2 0 0 1-2-2V5" /><path d="M16 14h.01" /></Svg>;
export const GearIcon = (p) => <Svg {...p}><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z" /></Svg>;
export const UserIcon = (p) => <Svg {...p}><path d="M20 21a8 8 0 0 0-16 0" /><circle cx="12" cy="8" r="4" /></Svg>;
export const LockIcon = (p) => <Svg {...p}><rect x="4" y="11" width="16" height="10" rx="2" /><path d="M8 11V7a4 4 0 0 1 8 0v4" /></Svg>;
export const WarningIcon = (p) => <Svg {...p}><path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0zM12 9v4M12 17h.01" /></Svg>;
export const CheckIcon = (p) => <Svg {...p}><path d="M20 6 9 17l-5-5" /></Svg>;

// The tab icons used in both side menus.
export const BotIcon = (p) => <Svg {...p}><rect x="4" y="8" width="16" height="12" rx="3" /><path d="M12 4v4M9 13h.01M15 13h.01M9 17h6" /></Svg>;
export const TAB_ICONS = { chat: ChatIcon, code: CodeIcon, cowork: SparkleIcon, design: BrushIcon, finance: WalletIcon, bots: BotIcon };
