document.getElementById('load-tabs-button').addEventListener('click', function () {
    const data = {
        "Source1": {
            "PGN1": ["SPN1", "SPN2"],
            "PGN2": ["SPN3", "SPN4"]
        },
        "Source2": {
            "PGN3": ["SPN5", "SPN6"],
            "PGN4": ["SPN7", "SPN8"]
        }
    };

    const tabLinksContainer = document.getElementById('tab-links');
    const tabContentsContainer = document.getElementById('tab-contents');
    const tabsContainer = document.getElementById('tabs-container');
    tabsContainer.style.display = 'flex';

    let firstTab = true;
    for (const source in data) {
        const tabButton = document.createElement('button');
        tabButton.textContent = source;
        tabButton.classList.add('tab-link');
        if (firstTab) {
            tabButton.classList.add('active');
        }
        tabLinksContainer.appendChild(tabButton);

        const tabContent = document.createElement('div');
        tabContent.classList.add('tab-content');
        if (firstTab) {
            tabContent.classList.add('active');
        }

        for (const pgn in data[source]) {
            const pgnElement = document.createElement('h3');
            pgnElement.textContent = pgn;
            tabContent.appendChild(pgnElement);

            const spnList = document.createElement('ul');
            data[source][pgn].forEach(spn => {
                const spnItem = document.createElement('li');
                spnItem.textContent = spn;
                spnList.appendChild(spnItem);
            });
            tabContent.appendChild(spnList);
        }

        tabContentsContainer.appendChild(tabContent);
        firstTab = false;
    }

    document.querySelectorAll('.tab-link').forEach(button => {
        button.addEventListener('click', () => {
            document.querySelectorAll('.tab-link').forEach(btn => btn.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(content => content.classList.remove('active'));

            button.classList.add('active');
            const index = Array.from(button.parentNode.children).indexOf(button);
            document.querySelectorAll('.tab-content')[index].classList.add('active');
        });
    });
});
