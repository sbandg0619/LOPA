# lcu_probe.py
import time
from lcu_client import LCUClient

def main():
    lcu = LCUClient.from_env_or_guess()
    ok, msg = lcu.ping()
    print("PING:", ok, msg)
    for i in range(10):
        st = lcu.get_champ_select_state()
        ids = lcu.extract_ids(st)
        print(f"[{i}] phase={st['phase']} myTurn={st['isMyTurn']} picks={ids['my_picks']} vs={ids['their_picks']} bans={ids['my_bans']}|{ids['their_bans']}")
        time.sleep(1)

if __name__ == "__main__":
    main()
