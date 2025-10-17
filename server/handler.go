package main

import (
	"fmt"
	"net/http"
	"path/filepath"

	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
)

var secretApiKey = "SUDEV_TOPLULUK_2025"

type Router struct {
	UploadDir string
	BaseUrl   string
	Router    *gin.Engine
}

func NewRouter(baseUrl string, uploadDir string, router *gin.Engine) *Router {
	return &Router{
		UploadDir: uploadDir,
		BaseUrl:   baseUrl,
		Router:    router,
	}
}

func (r *Router) Routers() {
	r.Router.Static("/uploads", r.UploadDir)
	api := r.Router.Group("/")
	{
		api.POST("/upload", r.UploadPhoto())
	}
}

func (r *Router) UploadPhoto() gin.HandlerFunc {
	return func(ctx *gin.Context) {

		// API KEY CONTROL
		clientKey := ctx.PostForm("api_key")
		if clientKey != secretApiKey {
			ctx.JSON(http.StatusUnauthorized, gin.H{
				"success": false,
				"error":   "Invalid API_KEY",
			})
			return
		}
		// PHOTO CONTROL
		file, err := ctx.FormFile("photo")
		if err != nil {
			ctx.JSON(http.StatusBadRequest, gin.H{
				"status":  "error",
				"success": false,
				"error":   "Photo not found",
			})
			return
		}

		extension := filepath.Ext(file.Filename)
		uniqueFileName := fmt.Sprintf("%s%s", uuid.New().String(), extension)
		destinationPath := filepath.Join(r.UploadDir, uniqueFileName)

		if err := ctx.SaveUploadedFile(file, destinationPath); err != nil {
			ctx.JSON(http.StatusInternalServerError, gin.H{
				"success": false,
				"error":   "Can not save",
			})
			return
		}
		fileUrl := fmt.Sprintf("%s/uploads/%s", r.BaseUrl, uniqueFileName)

		ctx.JSON(http.StatusOK, gin.H{
			"status":       "success",
			"success":      true,
			"download_url": fileUrl,
		})
		return
		//og.Printf("File URL: %s", fileUrl)

		//qrCodePNG, err := qrcode.Encode(fileUrl, qrcode.Medium, 256)
		//if err != nil {
		//	ctx.JSON(http.StatusInternalServerError, gin.H{"error": "Can not create QR-Code."})
		//	return
		//}
		//ctx.Data(http.StatusOK, "image/png", qrCodePNG)
	}
}
