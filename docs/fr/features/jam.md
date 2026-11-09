---
icon: lucide/users
---

# Jam

Une Jam permet à plusieurs comptes d’écouter ensemble. Une personne la lance, les autres la rejoignent avec son code, et chacun ajoute des titres à la même file. Chaque appareil de la Jam joue le même titre au même moment, sur ses propres enceintes ou son propre casque.

Les Jams demandent des [comptes](users.md) : chaque membre se connecte au même serveur Castify avec son propre compte. Seuls les titres déjà présents dans la bibliothèque peuvent être ajoutés.

## Lancer une Jam

Ouvrez **Jam** dans le menu latéral (sur téléphone : **Plus → Jam**), ou le bouton en forme de personnes dans la barre du lecteur, puis :

- **Lancer une Jam** en ouvre une vide.
- **Lancer avec la lecture en cours** emporte dans la nouvelle Jam le titre en cours (à la même position) et les titres qui le suivent dans votre file.

La page affiche alors le code à six caractères de la Jam. **Copier le code** et **Copier le lien** vous donnent de quoi l’envoyer : le lien ouvre la page Jam avec le code déjà rempli.

## Rejoindre une Jam

Sur la page Jam, tapez le code sous **Rejoindre une Jam** (majuscules, espaces et tirets n’ont pas d’importance ; un lien d’invitation collé marche aussi) puis appuyez sur **Rejoindre**. Rejoindre une autre Jam quitte celle où vous étiez.

Dès que vous rejoignez, votre lecteur passe sur la file de la Jam et se cale sur le titre et la position des autres.

## Ajouter des titres

Pendant une Jam, les actions de file habituelles alimentent la Jam au lieu de votre propre file :

- **Ajouter à la file** place les titres à la fin de la Jam.
- **Lire ensuite** les place juste après le titre en cours.
- **Lire** sur un titre, un album ou une playlist le place juste après le titre en cours et le lance, pour tout le monde.

La page Jam liste la file partagée avec qui a ajouté chaque titre. Chacun peut retirer un titre qu’il a ajouté.

::: info Les flux ne rejoignent pas la Jam
Les titres seulement diffusés en streaming (résultats de recherche, Découvrir, classements) ne peuvent pas entrer dans une Jam : tout le monde lit le même fichier de la bibliothèque. Téléchargez d’abord un titre pour le partager.
:::

## Piloter la lecture

Lecture, pause, précédent, suivant et déplacement dans le titre — depuis la barre du lecteur, le lecteur plein écran, les touches multimédia ou la page Jam — agissent sur la Jam pour tout le monde. Un titre qui se termine fait passer toute la Jam au suivant.

L’hôte peut désactiver **Les invités peuvent piloter la lecture** sur la page Jam. Seul l’hôte peut alors lire, mettre en pause, passer, se déplacer, réordonner ou retirer les titres des autres ; les invités peuvent toujours ajouter des titres et retirer les leurs.

Aléatoire, répétition et lecture automatique sont désactivés pendant une Jam : la file partagée se lit dans son ordre.

## Écouter sur un autre appareil

**Écouter sur cet appareil** (activé par défaut, mémorisé par navigateur) décide si cet appareil produit du son. Désactivez-le pour utiliser un ordinateur ou un téléphone comme télécommande d’une Jam jouée sur un autre appareil — vos commandes marchent toujours et le lecteur montre toujours où en est le titre.

## Quitter et terminer

**Quitter** vous sort de la Jam ; votre lecteur garde sa file, en pause. Quand l’hôte appuie sur **Terminer la Jam**, elle se termine pour tout le monde.

Une Jam vit dans la mémoire du serveur : redémarrer le serveur termine toutes les Jams, et une Jam que personne n’a touchée depuis 12 heures est fermée.

## Comment les appareils restent synchronisés

Le serveur tient l’horloge de la Jam : le titre en cours, la position où il en était et à quel moment, et s’il joue. Chaque changement est envoyé aux membres par le [WebSocket](../api-reference.md#websocket), et chaque appareil en déduit où le titre devrait en être. Un appareil décalé de plus de deux secondes se recale, ce qu’il vérifie toutes les quelques secondes pendant la lecture.

Les endpoints sont listés sous [Jam](../api-reference.md#jam) dans la référence de l’API.
