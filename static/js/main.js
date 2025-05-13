// static/js/main.js
// Este arquivo pode ser usado para scripts globais ou
// interações mais complexas que não dependem diretamente de `url_for`.

$(document).ready(function() {
    // Exemplo: tooltip do bootstrap
    // $('[data-toggle="tooltip"]').tooltip();

    console.log("PetEncontra JS carregado.");
});

// Se você mover a lógica de encerrarBusca para cá:
// window.encerrarBusca = function(petId) { ... }
// Mas lembre-se que `fetch(\`/encerrar_busca/\${petId}\`, ...)`
// funcionará bem se o JS for carregado após a definição da rota base.