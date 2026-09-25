import { ChatMessage } from '../types';

interface MessageListProps {
  messages: ChatMessage[];
  isLoading: boolean;
}

export function MessageList({ messages, isLoading }: MessageListProps) {
  return (
    <div className="message-list" aria-live="polite">
      {messages.map((message) => (
        <article className={`message message-${message.role}`} key={message.id}>
          <div className="message-role">
            {message.role === 'user' ? '你' : 'AI Copilot'}
          </div>
          <div className="message-content">{message.content}</div>
        </article>
      ))}

      {isLoading && (
        <article className="message message-assistant">
          <div className="message-role">AI Copilot</div>
          <div className="message-content">正在思考...</div>
        </article>
      )}
    </div>
  );
}

