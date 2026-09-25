import { FormEvent, useState } from 'react';

interface ChatInputProps {
  disabled: boolean;
  onSend: (message: string) => void;
}

export function ChatInput({ disabled, onSend }: ChatInputProps) {
  const [message, setMessage] = useState('');

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const trimmedMessage = message.trim();
    if (!trimmedMessage || disabled) {
      return;
    }

    onSend(trimmedMessage);
    setMessage('');
  }

  return (
    <form className="chat-input" onSubmit={handleSubmit}>
      <input
        aria-label="Message"
        disabled={disabled}
        placeholder="输入你的问题..."
        value={message}
        onChange={(event) => setMessage(event.target.value)}
      />
      <button disabled={disabled || !message.trim()} type="submit">
        发送
      </button>
    </form>
  );
}

