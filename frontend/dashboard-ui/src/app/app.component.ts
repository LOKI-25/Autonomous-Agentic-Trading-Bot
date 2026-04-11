import { Component, OnInit, OnDestroy } from '@angular/core';
import { Subject, takeUntil } from 'rxjs';
import { TradeService } from './services/trade.service';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { environment } from '../environments/environment';

interface ChatThread {
  id: string;
  title: string;
  messages: { role: 'user' | 'bot', content: string }[];
}

@Component({
  imports: [CommonModule, FormsModule],
  selector: 'app-root',
  templateUrl: './app.component.html'
})
export class AppComponent implements OnInit, OnDestroy {
  trades: any[] = [];
  isLoading = false;

  // --- New Chat Interface State ---
  activeTab: 'dashboard' | 'chat' = 'dashboard';
  chatInput: string = '';
  messages: { role: 'user' | 'bot', content: string }[] = [];
  isTyping: boolean = false;
  currentThreadId: string | null = null;
  threads: ChatThread[] = [];

  apiUrl = environment.apiUrl; 

  // This is used to clean up subscriptions when the component is destroyed
  private destroy$ = new Subject<void>();

  constructor(private tradeService: TradeService) {}

  ngOnInit() {
    this.loadThreadsFromDatabase();

    // Start the real-time stream
    this.tradeService.getTradeUpdates()
      .pipe(takeUntil(this.destroy$)) // Auto-unsubscribe!
      .subscribe({
        next: (data) => {
          this.trades = data.trades || [];
          this.isLoading = false;
          console.log('Real-time portfolio sync complete.');
        },
        error: (err) => {
          console.error('SSE Connection failed:', err);
          this.isLoading = false;
        }
      });
  }

  // Handle Approve/Reject
  handleAction(id: string, action: 'approve' | 'reject') {
    this.isLoading = true; // Visual feedback for the manager
    
    const request = action === 'approve' 
      ? this.tradeService.approveTrade(id) 
      : this.tradeService.rejectTrade(id);
    
    request.pipe(takeUntil(this.destroy$)).subscribe({
      next: () => {
        // NOTE: We do NOT call refreshTrades() here.
        // We trust the SSE stream to push the update once the DB changes.
        console.log(`Action ${action} sent for Trade ID: ${id}`);
      },
      error: (err) => {
        console.error('Action failed:', err);
        this.isLoading = false;
      }
    });
  }

  async sendMessage() {
    if (!this.chatInput.trim()) return;
    
    const userText = this.chatInput;
    
    // Optimistically add user message to the UI
    this.messages.push({ role: 'user', content: userText });
    this.chatInput = '';
    this.isTyping = true;

    // Save the new user message locally if we are already in a thread
    if (this.currentThreadId) {
      this.saveThreadsToDatabase();
    }

    try {
      const response = await fetch(`${this.apiUrl}/trade`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: userText, thread_id: this.currentThreadId })
      });
      
      const data = await response.json();
      
      // If this is a brand new chat, create a new thread in the sidebar
      if (!this.currentThreadId) {
        this.currentThreadId = data.trade_id;
        
        // Try to extract the asset name from the first message (e.g. "APPLE")
        const words = userText.replace(/[^a-zA-Z0-9 ]/g, '').split(' ').filter(w => w);
        const action = words.find(w => ['buy', 'sell'].includes(w.toLowerCase()));
        const skipWords = ['shares', 'of', 'the', 'a', 'an'];
        const target = action ? words.slice(words.indexOf(action) + 1).find(w => isNaN(Number(w)) && !skipWords.includes(w.toLowerCase())) : null;
        
        this.threads.unshift({
          id: data.trade_id,
          title: `${target ? target.toUpperCase() : 'TRADE'} - ${data.trade_id}`,
          messages: this.messages // Point the thread to our active messages array
        });
      }
      this.messages.push({ role: 'bot', content: data.message });
      this.saveThreadsToDatabase();
    } catch (error) {
      this.messages.push({ role: 'bot', content: 'System Error: Failed to communicate with the trading agent.' });
      if (this.currentThreadId) this.saveThreadsToDatabase();
    } finally {
      this.isTyping = false;
    }
  }

  newChat() {
    this.currentThreadId = null;
    this.messages = [];
  }

  selectThread(id: string) {
    const thread = this.threads.find(t => t.id === id);
    if (thread) {
      this.currentThreadId = thread.id;
      this.messages = thread.messages;
    }
  }

  loadThreadsFromDatabase() {
    fetch(`${this.apiUrl}/chat-threads`)
      .then(res => res.json())
      .then(data => {
        this.threads = data;
      })
      .catch(err => console.error('Failed to load threads from DB', err));
  }

  saveThreadsToDatabase() {
    if (!this.currentThreadId) return;
    const currentThread = this.threads.find(t => t.id === this.currentThreadId);
    if (currentThread) {
      fetch(`${this.apiUrl}/sync-chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(currentThread)
      }).catch(err => console.error('Failed to sync thread', err));
    }
  }

  ngOnDestroy() {
    // This tells all observables to stop when the user leaves the page
    this.destroy$.next();
    this.destroy$.complete();
  }
}