import sqlite3
c = sqlite3.connect('agent_krypto.db')

# Check remaining data
for t in ['simulated_trades', 'decisions', 'learning_log', 'features']:
    cur = c.execute(f'SELECT COUNT(*) FROM {t}')
    print(f'{t}: {cur.fetchone()[0]} rows')

# Delete learning_log (FK to decisions)
c.execute('DELETE FROM learning_log')
c.commit()
print('Deleted learning_log:', c.total_changes)

# Double-check simulated_trades
c.execute('DELETE FROM simulated_trades')
c.commit()
print('Deleted simulated_trades:', c.total_changes)

# Re-verify
for t in ['simulated_trades', 'decisions', 'learning_log', 'features']:
    cur = c.execute(f'SELECT COUNT(*) FROM {t}')
    print(f'{t}: {cur.fetchone()[0]} rows')

c.close()
