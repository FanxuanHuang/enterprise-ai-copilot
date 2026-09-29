import { useState } from 'react';
import { sendChatMessage } from './api/chatApi';
import { ChatInput } from './components/ChatInput';
import { MessageList } from './components/MessageList';
import { StatusMessage } from './components/StatusMessage';
import { ChatMessage } from './types';
import './App.css';

function createMessage(role: ChatMessage['role'], content: string): ChatMessage {
  return {
    id: crypto.randomUUID(),
    role,
    content,
  };
}

export default function App() {
  const [messages, setMessages] = useState<ChatMessage[]>([
    createMessage('assistant', '你好，我是 Enterprise AI Copilot。你可以先问我一个问题。'),
  ]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState('');

  async function handleSend(message: string) {
    setError('');
    setIsLoading(true);
    setMessages((currentMessages) => [
      ...currentMessages,
      createMessage('user', message),
    ]);

    try {
      const answer = await sendChatMessage(message);
      setMessages((currentMessages) => [
        ...currentMessages,
        createMessage('assistant', answer),
      ]);
    } catch (requestError) {
      const errorMessage =
        requestError instanceof Error
          ? requestError.message
          : '请求失败，请稍后重试。';
      setError(errorMessage);
    } finally {
      setIsLoading(false);
    }
  }

  return (
    <main className="app-shell">
      <section className="chat-panel" aria-label="Enterprise AI Copilot Chat">
        <header className="chat-header">
          <div>
            <p className="eyebrow">Enterprise AI Copilot</p>
            <h1>企业 AI 助手</h1>
          </div>
          <span className="version-badge">V3</span>
        </header>

        <MessageList messages={messages} isLoading={isLoading} />
        {error && <StatusMessage message={error} />}
        <ChatInput disabled={isLoading} onSend={handleSend} />
      </section>
    </main>
  );
}
