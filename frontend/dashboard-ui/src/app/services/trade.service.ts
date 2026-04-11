import { Injectable, NgZone } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';

@Injectable({ providedIn: 'root' })
export class TradeService {
  private apiUrl = environment.apiUrl; // Use environment variable for API URL

  constructor(private http: HttpClient, private zone: NgZone) {}

  getPendingTrades(): Observable<any[]> {
    return this.http.get<any[]>(`${this.apiUrl}/pending-trades`);
  }

  approveTrade(id: string): Observable<any> {
    return this.http.post(`${this.apiUrl}/approve/${id}`, {});
  }

  rejectTrade(id: string): Observable<any> {
    return this.http.post(`${this.apiUrl}/reject/${id}`, {});
  }

  getTradeUpdates(): Observable<any> {
    // EventSource is browser-only. Guard for SSR / non-browser environments.
    if (typeof window === 'undefined' || typeof EventSource === 'undefined') {
      return new Observable(observer => {
        observer.next({ trades: [] });
        observer.complete();
      });
    }

    return new Observable(observer => {
      const eventSource = new EventSource(`${this.apiUrl}/stream-trades`);
      
      eventSource.onmessage = (event) => {
        this.zone.run(() => {
          observer.next(JSON.parse(event.data));
        });
      };

      eventSource.onerror = (error) => {
        this.zone.run(() => observer.error(error));
      };
      
      return () => eventSource.close();
    });
  }
}