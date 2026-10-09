# Compta kiné remplaçant

Petite appli Streamlit pour suivre mes remplacements : saisie par semaine, récapitulatif par semaine / mois / année,
net gagné et estimation de ce que je peux me virer après cotisations et impôt.

## Lancer en local (recommandé)

```bash
pip install -r requirements.txt
streamlit run app.py
```

Les données sont enregistrées dans `data/compta.json` (créé automatiquement, ignoré par git).
Pense à télécharger une sauvegarde de temps en temps depuis la barre latérale.

## Si je la déploie en ligne (Streamlit Community Cloud)

- Le dépôt GitHub doit être **privé**.
- Le disque du serveur est **temporaire** : les données peuvent disparaître au redémarrage de l'appli.
  Télécharger la sauvegarde après chaque saisie, et la restaurer si besoin (barre latérale).
- Protéger l'appli par mot de passe : dans les « Secrets » de l'appli, ajouter

  ```toml
  APP_PASSWORD = "mon-mot-de-passe"
  ```

## Réglages à affiner (barre latérale)

- Cotisations URSSAF + CARPIMKO : 50 % au départ
- Impôt estimé : 10 % au départ
- Rétrocession par défaut : 20 % au départ (modifiable pour chaque semaine saisie)
