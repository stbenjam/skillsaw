export default function register(pi: { registerCommand(name: string, run: () => void): void }) {
  pi.registerCommand("review", () => {});
}
