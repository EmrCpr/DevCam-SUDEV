package main

import (
	"log"
	"os"

	"github.com/gin-gonic/gin"
)

const serverBaseUrl = "http://localhost:8080"
const uploadDir = "./uploads"

func main() {
	if err := os.MkdirAll(uploadDir, 0755); err != nil {
		log.Fatalf("Uploads directory can not create %v", err)
	}
	r := gin.Default()

	router := NewRouter(serverBaseUrl, uploadDir, r)
	router.Routers()
	if err := router.Router.Run(":8080"); err != nil {
		log.Fatalf("Router can not open %v", err)
	}
}
